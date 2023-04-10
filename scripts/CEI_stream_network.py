import arcpy


def CEI_extraction(DEM_input,
                   precipitation,
                   evapotranspiration,
                   CEI_threshold,
                   rivers_output,
                   text_output,
                   out_flow_dir,
                   out_flow_acc,
                   out_CEI,
                   out_stream_links,
                   out_stream_orders,
                   out_watersheds):
    # Prepare environments
    arcpy.env.overwriteOutput = True
    arcpy.env.extent = DEM_input
    arcpy.env.snapRaster = DEM_input
    arcpy.env.cellSize = DEM_input
    arcpy.env.mask = DEM_input
    cell_x = arcpy.GetRasterProperties_management(DEM_input, "CELLSIZEX").getOutput(0)
    cell_y = arcpy.GetRasterProperties_management(DEM_input, "CELLSIZEY").getOutput(0)
    cell_area = float(cell_x.replace(',','.')) * float(cell_y.replace(',','.'))  # cell area in sq. m

    # Detect output rivers format
    if (rivers_output[-4:] == '.shp'):
        output_format = 'SHAPE'
    else:
        output_format = 'GDB'

    # Calculate slope
    arcpy.AddMessage('Calculating slope')
    slope_percent = arcpy.sa.Slope(DEM_input, "PERCENT_RISE")
    slope_tangent = arcpy.sa.Times(slope_percent, 0.01)
    arcpy.Delete_management('slope_percent')
    # slope_tangent.save('slope')  # left for debugging purposes
    
    # Calculate P - ET
    # TODO: Предусмотреть возможность задания разности сразу, без явного ввода осадков и испаряемости
    arcpy.AddMessage('Calculating P - ET')
    overland_flow = arcpy.sa.Minus(precipitation, evapotranspiration)  # for some unclear reason, simple '-' does not work there
    overland_flow_m = overland_flow * 0.001
    
    # DEM Hydro-processing
    # Fill in sinks
    arcpy.AddMessage('Fill in sinks')
    DEM_fill = arcpy.sa.Fill(DEM_input)
    # Calculate flow directions
    arcpy.AddMessage('Calculating flow directions')
    flow_directions = arcpy.sa.FlowDirection(DEM_fill, "NORMAL", 'slope_percent')
    # Save output flow direction as optional parameter
    if out_flow_dir and out_flow_dir != "#":
        arcpy.AddMessage('Saving flow directions')
        flow_directions.save(out_flow_dir)
    # Calculate flow accumulation
    arcpy.AddMessage('Calculating flow accumulation with overland flow')
    flow_accumulation = arcpy.sa.FlowAccumulation(flow_directions, overland_flow_m)
    if out_flow_acc and out_flow_acc != "#":
        arcpy.AddMessage('Saving flow accumulation')
        flow_accumulation.save(out_flow_acc) 
    # flow_accumulation.save('FlowAcc')  # DEBUG

    # Calculate CEI
    arcpy.AddMessage('Calculating CEI')
    CEI = flow_accumulation * cell_area * slope_tangent
    if out_CEI and out_CEI != "#":
        arcpy.AddMessage('Saving CEI raster')
        CEI.save(out_CEI) 
    # CEI.save('CEI_debug')  # DEBUG
    
    # Reconstructing river network (raster)
    # Extracting initial cells
    arcpy.AddMessage('Extracting initial cells')
    initials = arcpy.sa.Con(CEI, '1', '0', "Value > %s" % (CEI_threshold))
    # initials.save('Initials')  # DEBUG
    # Calculating flow accumulation again to reconstuct connected stream network
    arcpy.AddMessage('Reconstructing stream network')
    flow_accumulation_streams = arcpy.sa.FlowAccumulation(flow_directions, initials)
    # Exctacting stream cells
    arcpy.AddMessage('Extracting stream network')
    stream_cells0 = arcpy.sa.Con(flow_accumulation_streams, '1', '0', "Value > 0")
    # Combining stream cells and initials
    stream_cells = arcpy.sa.BooleanOr(initials, stream_cells0)
    # stream_cells.save('stream_cells')  # DEBUG
    
    # Extract streams
    arcpy.AddMessage('Extract vector streams')
    stream_links = arcpy.sa.StreamLink(stream_cells, flow_directions)

    #TODO: реализовать фильтрацию водотодов 1 порядка по длине

    if out_stream_links and out_stream_links != '#':
        stream_links.save(out_stream_links)
    stream_orders = arcpy.sa.StreamOrder(stream_cells, flow_directions, "STRAHLER")
    if out_stream_orders and out_stream_orders != '#':
        stream_orders.save(out_stream_orders)
    else:
        out_stream_orders = 'stream_order'
        stream_orders.save(out_stream_orders)
    arcpy.sa.StreamToFeature(stream_orders, flow_directions, 'streams_output', "SIMPLIFY")
    # Changing field name to a meaningful string
    arcpy.AlterField_management('streams_output', 'grid_code', 'strahler_order', "Strahler order")
    arcpy.AddMessage('Delineating watersheds')
    outWatersheds_raster = arcpy.sa.Watershed(flow_directions, stream_links)
    # outWatersheds_raster.save(out_watersheds)  # DEBUG
    if out_watersheds and out_watersheds != '#':
        arcpy.RasterToPolygon_conversion(outWatersheds_raster, out_watersheds, "NO_SIMPLIFY", "", "MULTIPLE_OUTER_PART")
        #TODO: получать сведения о порядке соответствующего водотока из растра порядков водотоков

    # Join streams with equal Strahler order
    arcpy.AddMessage('Dissolving streams')
    # Working with Stream order raster attribute table
    # Build attribute table
    arcpy.BuildRasterAttributeTable_management(out_stream_orders)
    # Extract values
    values = [i[0] for i in arcpy.da.SearchCursor(out_stream_orders, "Value")]
    arcpy.AddMessage("Strahler orders are: " + str(values))
    # Dissolve streams by Strahler order
    arcpy.Dissolve_management('streams_output', 'streams_output_dissolve', 'strahler_order', "", "SINGLE_PART", "DISSOLVE_LINES")
    # Extract both ends from dissolved streams
    arcpy.FeatureVerticesToPoints_management('streams_output_dissolve', 'streams_output_end', "BOTH_ENDS")
    # Split 'V-shaped' dissolved streams at end points
    fc_list = []
    # Set radius for splitting
    split_radius = '1 Meters'
    # Processing each order separately
    for i in values:
        # Selecting streams to split
        expr = "strahler_order = " + str(i)
        arcpy.MakeFeatureLayer_management('streams_output_dissolve', "streams_selection", expr)
        # Selecting points to split. They have i+1 order
        expr = "strahler_order = " + str(i + 1)
        arcpy.MakeFeatureLayer_management('streams_output_end', "points_selection", expr)
        # Split selected streams at selected points
        rivers_temp = 'rivers_%s_order' % (i)  # Set dataset name
        fc_list.append(rivers_temp)
        arcpy.SplitLineAtPoint_management("streams_selection", "points_selection", rivers_temp, split_radius)
    # Merging streams
    arcpy.Merge_management(fc_list, rivers_output)
    # Deleting temporary feature classes
    arcpy.Delete_management('streams_output_dissolve')
    arcpy.Delete_management('streams_output_end')
    for fc in fc_list:
        arcpy.Delete_management(fc)

    # Calculate mean slope within streams
    # TODO: добавить вычисление средней высоты
    arcpy.AddMessage('Calculate mean slope')
    # Extract drop values by mask
    drop_raster_streams = arcpy.sa.ExtractByMask('slope_percent', stream_orders)
    # Perform zonal statistics; result is saved as raster
    drop_raster_mean = arcpy.sa.ZonalStatistics(outWatersheds_raster, 'Value', drop_raster_streams, "MEAN")
    # Extract rivers startpoints
    arcpy.FeatureVerticesToPoints_management(rivers_output, 'rivers_startpoints', "START")
    # Extract zonal statistics raster values to rivers' startpoints
    arcpy.sa.ExtractValuesToPoints('rivers_startpoints', drop_raster_mean, 'rivers_startpoints_stat')
    arcpy.Delete_management('rivers_startpoints')
    # Join point attribute table to rivers, transfer attributes
    arcpy.AddField_management(rivers_output, 'Mean_slope', "FLOAT")
    arcpy.MakeFeatureLayer_management(rivers_output, 'rivers_layer')
    if output_format == 'SHAPE':
        target_field = 'FID'
    else:
        target_field = 'OBJECTID'
    arcpy.AddJoin_management('rivers_layer', target_field, 'rivers_startpoints_stat', "ORIG_FID")
    arcpy.CalculateField_management('rivers_layer', "Mean_slope", "!rivers_startpoints_stat.RASTERVALU!", "PYTHON_9.3")
    # Remove join
    arcpy.RemoveJoin_management('rivers_layer')
    # Delete temporary file
    arcpy.Delete_management('rivers_startpoints_stat')

    # Compute number of streams and total length
    # Computation is performed over simplified streams to reduce error
    # Compute total river length
    arcpy.AddMessage('Compute river length and number of segments')
    total_length = float(sum(row[0] for row in arcpy.da.SearchCursor(rivers_output, 'SHAPE@LENGTH')))
    total_count = arcpy.GetCount_management(rivers_output)
    
    # Compute statistics by order   
    # Count number and total length for every order
    order_length = []
    order_count = []
    for i in values:
        if output_format == 'SHAPE':
            expr = "strahler_o = " + str(i)
        else:
            expr = "strahler_order = " + str(i)
        arcpy.MakeFeatureLayer_management(rivers_output, "rivers_selection", expr)
        order_length.append(float(sum(row[0] for row in arcpy.da.SearchCursor("rivers_selection", 'SHAPE@LENGTH'))))
        order_count.append(arcpy.GetCount_management("rivers_selection"))

    # Delete Strahler order raster if not saved explicitly
    if out_stream_orders and out_stream_orders != '#':
        arcpy.Delete_management('stream_order')

    # Write parameters to the output text file
    arcpy.AddMessage('Save statistics to the text file')
    with open(text_output, 'w') as out:
        out.write('Total river length: ' + str(total_length) + ' m\n')
        out.write('Total count: ' + str(total_count) + '\n')
        for i in values:  # array starts at 0, but orders start from 1, so [i-1]
            if i == 1:
                suffix = "nd "
            elif i == 2:
                suffix = 'rd '
            else:
                suffix = 'st '
            out.write(str(i) + suffix + 'order length: '+ str(order_length[i-1]) + 'm \n')
            out.write(str(i) + suffix + 'order count: ' + str(order_count[i-1]) + '\n')
    #TODO: средняя длина, средний уклон, средняя площадь водосбора
    return


if __name__ == '__main__':
    # Arguments are optional
    args = tuple(arcpy.GetParameterAsText(i)
                 for i in range(arcpy.GetArgumentCount()))
    CEI_extraction(*args)