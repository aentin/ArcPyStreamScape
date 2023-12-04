import math
import arcpy
from arcpy import env
from arcpy.sa import *


def Watershed_extraction(flow_directions, 
                         rivers_input, 
                         watersheds_output,
                         text_output):
    # Compute stream order
    arcpy.AddMessage('Compute stream order')
    stream_links = StreamLink(rivers_input, flow_directions)
    stream_order = StreamOrder(rivers_input, flow_directions, "STRAHLER")
    stream_order.save('stream_order')  # This is not for debug. 
    # The stream_order raster is needed to extract unique stream order values

    # Extract unique values from stream order raster
    arcpy.BuildRasterAttributeTable_management('stream_order')
    values = [i[0] for i in arcpy.da.SearchCursor('stream_order',"Value")]
    arcpy.AddMessage(values)
    
    # Process orders consequently
    # Create empty lists for feature class (fc) and field names
    fc_list = []
    field_list =[]
    # Iterate Strahler orders
    for i in values:
        arcpy.AddMessage('Order processing: ' + str(i))
        streams_select = Con(stream_order == i, stream_links, '')  # Select current order (raster)
        watersheds_raster = Watershed(flow_directions, streams_select)  # Create watershed from streams_select
        watersheds_vector = 'Watershed_%s' % (i)  # Set dataset name
        fc_list.append(watersheds_vector)  # Append name to the list
        arcpy.RasterToPolygon_conversion(watersheds_raster, watersheds_vector, "NO_SIMPLIFY")  # Convert raster waterhsed to vector
        field_name = 'Strahler_order' + str(i)  # Create field name for current Strahler order
        field_list.append(field_name)  # Append the name to the field names list
        arcpy.AddField_management(watersheds_vector, field_name, "SHORT")  # Add field to store Strahler order
        cursor = arcpy.UpdateCursor(watersheds_vector)  # Fill field with current Strahler order values
        # Set Strahler order values for all the features
        for row in cursor:
            row.setValue(field_name, i)
            cursor.updateRow(row)

    # Converting polygons to lines
    arcpy.AddMessage('Converting polygons to lines')
    # Very nice trick here! ArcGIS allows to use multiple input polygons in Feature to Line!
    arcpy.FeatureToLine_management(fc_list, watersheds_output)  
    
    # Removing unwanted fields
    field_names = [f.name for f in arcpy.ListFields(watersheds_output)]  # Generating feild names list
    field_list_save = field_list[:]  # Duplicating variable field_list to 'unlink' them first
    field_list_save.extend(['Shape', 'OBJECTID', 'ID', 'FID', 'Shape_Length'])  # Add system fields to the list to avoid deleting them
    field_list_remove = [field_name for field_name in field_names if field_name not in field_list_save]  # Create list of fields to remove
    arcpy.DeleteField_management(watersheds_output, field_list_remove)  # Remove fields
    arcpy.Copy_management(watersheds_output, 'watersheds_line_withidentical')

    # Delete features with identical shape and Strahler orders (save only one)
    field_list_remove_duplicate = field_list[:]  # Duplicating variable field_list to 'unlink' them first
    field_list_remove_duplicate.append('Shape')  # Add system field to use for comparison
    arcpy.DeleteIdentical_management(watersheds_output, field_list_remove_duplicate)
    
    # Merge Strahler order fields
    arcpy.AddMessage("Merge Strahler order fields")
    arcpy.AddField_management(watersheds_output, 'watershed_order', "TEXT")  # Create new field
    # Create expression for field calculator
    values.reverse()
    # arcpy.AddMessage(values)
    concatenate_expression = ''
    for i in values:
        field_name = 'Strahler_order' + str(i) 
        concatenate_expression = concatenate_expression + 'str(!' +  field_name + '!)' + ' + '
    concatenate_expression = concatenate_expression[:-3]  # trim last 3 symbols, which are ' + '
    # arcpy.AddMessage(concatenate_expression)
    # Fill created field
    arcpy.CalculateField_management(watersheds_output, 'watershed_order', concatenate_expression, "PYTHON")
    # Delete initial Strahler order fields, leave only concatenation result
    arcpy.DeleteField_management(watersheds_output, field_list)

    # Reclass by full sequence and by highest triplet
    arcpy.AddMessage("Reclassify Strahler orders")
    arcpy.MakeFeatureLayer_management(watersheds_output, "selection_layer")  # Create layer for further selection
    
    # Full sequence
    # Create full sequence list
    list_full_sequence = []
    temp_string0 = ''
    values_temp = values[:]
    for i in range(len(values)):
        temp_string0 = str(values_temp.pop(-1)) + temp_string0
        temp_string1 = "%0" + temp_string0
        if len(temp_string1) > len(values):
            temp_string1 = temp_string1[-(len(values)):]
        # temp_string1 = temp_string0.zfill(len(values))
        list_full_sequence.append(temp_string1)
    list_full_sequence.reverse()
    # Create field (full sequence order)
    arcpy.AddField_management(watersheds_output, 'Full_sequence', "SHORT")
    # Fill field with values
    for i in range(len(values)):
        selection_expression = "watershed_order LIKE '%s'" % (list_full_sequence[i])
        arcpy.SelectLayerByAttribute_management("selection_layer", "NEW_SELECTION", selection_expression)
        arcpy.CalculateField_management("selection_layer", 'Full_sequence', values[i], "PYTHON")
    
    # Highest triplets
    # Create highest triplets list
    list_triplets = []
    temp_string0 = ''
    for i in range(len(values)):
        if i == len(values) - 1:
            temp_string0 = str(values[-1])
        elif i == len(values) - 2:
            temp_string0 = str(values[-2]) + str(values[-1])
        elif i == len(values) - 3:
            temp_string0 = str(values[-3]) + str(values[-2]) + str(values[-1])
        else:
            temp_string0 = str(values[i]) + str(values[i+1]) + str(values[i+2])
            temp_string0 = temp_string0 + '%'
        if i == 0:
            temp_string1 = temp_string0
        elif i == 1:
            temp_string1 = "0" + temp_string0
        else:
            temp_string1 = "%0" + temp_string0
        if len(temp_string1) > len(values):
            temp_string1 = temp_string1[-(len(values)):]
        list_triplets.append(temp_string1)
    # Create field (highest triplet order)
    arcpy.AddField_management(watersheds_output, 'Highest_triplet', "SHORT")
    # Fill field with values
    for i in range(len(values)):
        selection_expression = "watershed_order LIKE '%s' and Highest_triplet IS NULL" % (list_triplets[i])
        arcpy.SelectLayerByAttribute_management("selection_layer", "NEW_SELECTION", selection_expression)
        arcpy.CalculateField_management("selection_layer", 'Highest_triplet', values[i], "PYTHON")
    
    #TODO: рассчитать среднюю высоту для каждого сегмента

    #TODO: визуализировать оба -- предлагаю не делать
    # CLOSED: выдавать список параметров: Число сегментов каждого порядка, суммарная длина сегментов каждого порядка
    # Calculate total length and total number of segments
    arcpy.AddMessage('Compute watershed length and number of segments')
    # Total
    total_length = float(sum(row[0] for row in arcpy.da.SearchCursor(watersheds_output, 'SHAPE@LENGTH')))  # Total length
    total_count = arcpy.GetCount_management(watersheds_output)  # Total number of segments
    # Full order
    order_length_full = []
    order_count_full = []
    for i in values:
        expr = "Full_sequence = " + str(i)
        arcpy.MakeFeatureLayer_management(watersheds_output, "watersheds_selection", expr)
        order_length_full.append(float(sum(row[0] for row in arcpy.da.SearchCursor("watersheds_selection", 'SHAPE@LENGTH'))))
        order_count_full.append(arcpy.GetCount_management("watersheds_selection"))
    # Highest triplet
    order_length_triplet = []
    order_count_triplet = []
    for i in values:
        expr = "Highest_triplet = " + str(i)
        arcpy.MakeFeatureLayer_management(watersheds_output, "watersheds_selection", expr)
        order_length_triplet.append(float(sum(row[0] for row in arcpy.da.SearchCursor("watersheds_selection", 'SHAPE@LENGTH'))))
        order_count_triplet.append(arcpy.GetCount_management("watersheds_selection"))

    # Write parameters to the text file
    if text_output and text_output != "#":
        arcpy.AddMessage('Save statistics to the text file')
        with open(text_output, 'w') as out:
            out.write('Total watershed length: ' + str(total_length) + ' m\n')
            out.write('Total count: ' + str(total_count) + '\n')
            for i in values:  # array starts at 0, but orders start from 1, so [i-1]
                # if i == 1:
                #     suffix = "nd "
                # elif i == 2:
                #     suffix = 'rd '
                # else:
                suffix = ' '
                out.write(str(i) + suffix + 'order length (full sequence): ' + str(order_length_full[i-1]) + 'm \n')
                out.write(str(i) + suffix + 'order length (highest triplet): ' + str(order_length_triplet[i-1]) + 'm \n')
                out.write(str(i) + suffix + 'order count (full sequence): ' + str(order_count_full[i-1]) + '\n')
                out.write(str(i) + suffix + 'order count (highest triplet): ' + str(order_count_triplet[i-1]) + '\n')
    # TODO: проверить правильность расчётов и вывода

    return

if __name__ == '__main__':
    # Arguments are optional
    arcpy.env.overwriteOutput = True
    args = tuple(arcpy.GetParameterAsText(i)
                 for i in range(arcpy.GetArgumentCount()))
    Watershed_extraction(*args)