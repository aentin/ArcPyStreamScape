import math
import arcpy
from arcpy import env
from arcpy.sa import *


def Basin_parameters(DEM,
                     streams,
                     watersheds,
                     flow_directions,
                     watersheds_output,
                     mean_watershed_elevation,
                     mean_erosion_cut,
                     text_output):
    
    # # Prepare environments
    arcpy.env.overwriteOutput = True
    cell_x = float(arcpy.GetRasterProperties_management(DEM, "CELLSIZEX").getOutput(0))
    cell_y = float(arcpy.GetRasterProperties_management(DEM, "CELLSIZEY").getOutput(0))
    cell_area = cell_x * cell_y  # cell area in sq. m
    
    # Preprocessing
    arcpy.AddMessage('Preprocessing...')
    # Fill in sinks (required for analysis)
    DEM_fill = Fill(DEM)
    # Calculate flow directions (if not in input)
    if not (flow_directions and flow_directions != "#"):
        flow_directions = FlowDirection(DEM_fill, "NORMAL", 'slope_percent')
    # Calculate flow accumulation
    flow_accumulation = FlowAccumulation(flow_directions)
    # Check if watersheds are given as input data
    if watersheds and watersheds != '#':  # if yes, create a copy of input data
        arcpy.Copy_management(watersheds, watersheds_output)  # Note that 'watersheds' are feature class, not feature layer
    else:  # if not, delineate them
        stream_links = StreamLink(streams, flow_directions)
        watersheds_raster = Watershed(flow_directions, stream_links)
        arcpy.RasterToPolygon_conversion(watersheds_raster, watersheds_output, "NO_SIMPLIFY", "", "MULTIPLE_OUTER_PART")
    
    # Calculating watershed area (even if already exist)
    # Check if there is a field called Shape_Area:
    field_names = [f.name for f in arcpy.ListFields(watersheds_output)]
    # If not, add this field:
    if 'Shape_Area' not in field_names:
        arcpy.AddField_management(watersheds_output, 'Shape_Area', "DOUBLE")
        arcpy.CalculateField_management(watersheds_output, 'Shape_Area', '!shape.area!', 'PYTHON_9.3')
    
    # calculate sum of shape_area:
    sum_area = 0
    with arcpy.da.SearchCursor(watersheds_output, "Shape_Area") as cursor:
        for row in cursor:
            sum_area = sum_area + row[0]
    arcpy.AddMessage('Total shape area is: ' + str(sum_area))  # DEBUG

    # Perform zonal statistics as table
    ZonalStatisticsAsTable(watersheds_output, 'OBJECTID', DEM, 'stat_table_watersheds')
    # Join table with layer 'watersheds_output'
    arcpy.MakeFeatureLayer_management(watersheds_output, 'watersheds_layer')
    arcpy.AddJoin_management('watersheds_layer', "OBJECTID", 'stat_table_watersheds', "OBJECTID")
    # arcpy.RemoveJoin_management("watersheds_layer", "stat_table_watersheds")
    
    # Processings

    # 1: Extrema thickness
    arcpy.AddMessage('1: Extrema thickness...')
    # Assign elevation range to the new field
    expression = '!stat_table_watersheds.range!'
    arcpy.CalculateField_management('watersheds_layer', "deltaH_extr", expression, "PYTHON_9.3")
    # Compute 'extrema volume'
    expression = '!stat_table_watersheds.range! * !%s.Shape_Area!' % (watersheds_output.split('\\')[-1])
    arcpy.CalculateField_management('watersheds_layer', "V_extr", expression, "PYTHON_9.3")
    # Calculate final 'extrema thickness'
    sum_volume_extr = 0
    with arcpy.da.SearchCursor(watersheds_output, "V_extr") as cursor:
        for row in cursor:
            sum_volume_extr = sum_volume_extr + row[0]
    dH_extr = sum_volume_extr / sum_area
    # arcpy.AddMessage('dH_extr is: ' + str(dH_extr))  # DEBUG

    # 2: mean thickness
    arcpy.AddMessage('2: mean thickness...')
    # Extract stream elevations
    DEM_streams = ExtractByMask(DEM, streams)
    # Calculate zonal statistics for stream elevations
    ZonalStatisticsAsTable(watersheds_output, 'OBJECTID', DEM_streams, 'stat_table_streams')
    # Join calculated statistics to watersheds layer
    arcpy.AddJoin_management('watersheds_layer', "OBJECTID", 'stat_table_streams', "OBJECTID_1")
    # Compute 'mean elevation difference'
    arcpy.AddField_management(watersheds_output, 'deltaH_mean', 'Double')
    expression = '!stat_table_watersheds.mean! - !stat_table_streams.mean!'
    arcpy.CalculateField_management('watersheds_layer', "deltaH_mean", expression, "PYTHON_9.3")
    # Compute 'mean elevation volume'
    arcpy.AddField_management(watersheds_output, 'V_mean', 'Double')
    expression = '!deltaH_mean! * !%s.Shape_Area!' % (watersheds_output.split('\\')[-1])
    arcpy.CalculateField_management('watersheds_layer', "V_mean", expression, "PYTHON_9.3")
    # Calculate final 'mean thickness'
    sum_volume_mean = 0
    with arcpy.da.SearchCursor(watersheds_output, "V_mean") as cursor:
        for row in cursor:
            if row[0] is None:
                continue
            sum_volume_mean = sum_volume_mean + row[0]
    dH_mean = sum_volume_mean / sum_area
    arcpy.AddMessage('dH_mean is: ' + str(dH_mean))  # DEBUG

    # 3: watershed thickness
    arcpy.AddMessage('3: watershed thickness...')
    # Extract watersheds
    # Create inner buffer from watersheds
    buffer_distance = math.sqrt(cell_x**2 + cell_y**2) * (-1)
    arcpy.Buffer_analysis(watersheds_output, 'watersheds_buffer', buffer_distance)
    # Erase watershed polygons with buffer
    arcpy.Erase_analysis(watersheds_output, 'watersheds_buffer', 'watersheds_mask')
    # Select DEM cells with zero flow accumulation
    DEM_watersheds_lines = SetNull(flow_accumulation, DEM, "VALUE > 0")  #TODO: убрать это условие
    # Calculate zonal statistics for watershed lines
    ZonalStatisticsAsTable('watersheds_mask', 'OBJECTID', DEM_watersheds_lines, 'stat_table_watershed_lines')
    # Join zonal statistics with output watersheds
    arcpy.AddJoin_management('watersheds_layer', "OBJECTID", 'stat_table_watershed_lines', "OBJECTID")
    # Compute 'watershed elevation difference'
    arcpy.AddField_management(watersheds_output, 'deltaH_watershed', 'Double')
    expression = '!stat_table_watershed_lines.mean! - !stat_table_streams.mean!'
    arcpy.CalculateField_management('watersheds_layer', "deltaH_watershed", expression, "PYTHON_9.3")
    # Compute 'watershed elevation volume'
    arcpy.AddField_management(watersheds_output, 'V_watershed', 'Double')
    expression = '!deltaH_watershed! * !%s.Shape_Area!' % (watersheds_output.split('\\')[-1])
    arcpy.CalculateField_management('watersheds_layer', "V_watershed", expression, "PYTHON_9.3")
    # Calculate watershed 'watershed thickness'
    sum_volume_watershed = 0
    with arcpy.da.SearchCursor(watersheds_output, "V_watershed") as cursor:
        for row in cursor:
            if row[0] is None:
                continue
            sum_volume_watershed = sum_volume_watershed + row[0]
    dH_watershed = sum_volume_watershed / sum_area
    arcpy.AddMessage('dH_watershed is: ' + str(dH_watershed))  # DEBUG

    # Mean elevation, mean erosion cut, accumulated volume
    arcpy.AddMessage('4: continual parameters...')
    # catchment_area = flow_accumulation * cell_area
    sum_elevation_downstream = FlowAccumulation(flow_directions, DEM_fill)
    mean_watershed_elevation_raster = sum_elevation_downstream / flow_accumulation
    mean_watershed_elevation_raster.save(mean_watershed_elevation)  # средняя высота водосбора
    mean_erosion_cut_raster = mean_watershed_elevation_raster - DEM_fill
    mean_erosion_cut_raster.save(mean_erosion_cut)
    # TODO: сделать вывод: максимум вреза, величина вреза в замыкающем створе
    
    # Saving stats
    arcpy.AddMessage('Save statistics to the text file')
    with open(text_output, 'w') as out:
        out.write('Total volume by extrema: ' + str(sum_volume_extr) + ' m^3\n')
        out.write('dH by extrema: ' + str(dH_extr) + ' m\n')
        out.write('Total volume by mean: ' + str(sum_volume_mean) + ' m^3\n')
        out.write('dH by mean: ' + str(dH_mean) + ' m\n')
        out.write('Total volume by watershed lines: ' + str(sum_volume_watershed) + ' m^3\n')
        out.write('dH by watershed lines: ' + str(dH_watershed) + ' m\n')


if __name__ == '__main__':
    # Arguments are optional
    arcpy.env.overwriteOutput = True
    # arcpy.env.parallelProcessingFactor = '0'
    args = tuple(arcpy.GetParameterAsText(i)
                 for i in range(arcpy.GetArgumentCount()))
    Basin_parameters(*args)
