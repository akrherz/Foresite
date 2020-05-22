#!/usr/bin/env Python
import sys
import pathlib
import os
import xml.etree.ElementTree
from xml.etree.ElementTree import ElementTree, Element, SubElement
import pandas as pd
from analyses.munging import get_rotation
import io
import json
import apsim.wrapper as apsim

# Connect to database
dbconn = apsim.connect_to_database( 'database.ini' )

# # query scenarios to generate inputs
# SIM_NAME = 'huc12_test_job'
# START_DATE = '01/01/2016'
# END_DATE = '31/12/2018'
# INPUT_QUERY = 'select * from sandbox.huc12_inputs limit 0'
# input_tasks = pd.read_sql( INPUT_QUERY, dbconn )

# # constant spin up crops for multi-year rotation
cfs_mgmt = json.loads( open( 'crop_jsons/cfs.json', 'r' ).read() )
cc_mgmt = json.loads( open( 'crop_jsons/cc.json', 'r' ).read() )
sfc_mgmt = json.loads( open( 'crop_jsons/sfc.json', 'r' ).read() )

###
def get_date( date_str, year ):
    month_ids = {
        'jan': 1, 'feb': 2, 'mar': 3,
        'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9,
        'oct': 10, 'nov': 11, 'dec': 12
    }
    date = [ date_str.split( '-' )[0],
        month_ids[ date_str.split( '-' )[1] ],
        year ]
    date = '/'.join( [ str( d ) for d in date ] )

    return date

###
def add_management_year( man_ops, task, year ):
    ### primary tillage specs
    primary_till_imp = task[ 'spring_implement' ]
    primary_till_depth = task[ 'spring_depth' ]
    primary_till_incorp = task[ 'spring_residue_incorporation' ]
    primary_till_date = get_date( task[ 'spring_timing' ], year )
    man_ops.add_primary_till_op( primary_till_date, primary_till_imp, primary_till_incorp, primary_till_depth )

    ###secondary tillage specs
    secondary_till_imp = task[ 'fall_implement' ]
    secondary_till_depth = task[ 'fall_depth' ]
    secondary_till_incorp = task[ 'fall_residue_incorporation' ]
    secondary_till_date = get_date( task[ 'fall_timing' ], year )
    man_ops.add_secondary_till_op( secondary_till_date, secondary_till_imp, secondary_till_incorp, secondary_till_depth )

    ### fert specs
    n_rate = task[ 'kg_n_ha' ]
    n_type = task[ 'n_fertilizer' ]
    n_depth = task[ 'fert_depth' ]
    if n_rate != None and n_rate > 0.0:
        n_date = get_date( task[ 'fertilize_n_on' ], year )
        man_ops.add_fert_op( n_date, n_rate, n_depth, n_type )

    ### planting specs
    crop = task[ 'sow_crop' ]
    cult = task[ 'cultivar' ]
    dens = task[ 'sowing_density' ]
    depth = task[ 'sowing_depth' ]
    space = task[ 'row_spacing' ]

    plant_date = get_date( task[ 'planting_dates' ], year )
    man_ops.add_plant_op( plant_date, crop, dens, depth, cult, space )

    harvest_crop = crop
    if crop == 'maize':
        harvest_date = str ( '15-oct' )
    elif crop == 'soybean':
        harvest_date = str ( '5-oct' )
    harvest_date = get_date( harvest_date, year )
    man_ops.add_harvest_op( harvest_date, harvest_crop )

    return

#def create_input_table(dbconn, table, fip, start_year=2016, end_year=2018, id_col='fips', geo_col='wkb_geometry', name_col='county', soil_col="mukey", limit=False):
def create_apsim_files(df, rotations_df, dbconn, field_key='clukey', soil_key='mukey', county_col='county', rotation_col='rotation', crop_col='crop', start_year=2016, end_year=2018):
    if not os.path.exists('apsim_files'):
        os.makedirs('apsim_files')
    start_date = f'01/01/{start_year}'
    end_date = f'31/12/{end_year}'
    #save rotation for clukey to crops list
    #loop through field keys e.g., clukeys
    sim_count = 0
    for i in df[field_key]:
        field_id = i
        #get field information
        #TODO get 'clukey' and 'county' to work as function inputs instead of hardcoded
        field = df.loc[df['clukey'] == i]
        #get field rotation
        rotation_row = rotations_df.loc[rotations_df[field_key] == i]
        rotation = get_rotation(rotations_df, crop_col)
        #get unique soil keys e.g., mukeys
        soils = field.drop_duplicates(soil_key)
        runs = soils['mukey']
        #get weather file for desired county
        county_name = field.iloc[0]['county'].replace(" ", "_")
        met_name = f"{county_name}.met"
        met_path = f"met_files/{met_name}"
        #create apsim file for each unique soil in field
        for i in runs:
            try:
                soil_id = i
                soil_query = '''select * from api.get_soil_properties( array[{}]::text[] )'''.format( i )
                soil_df = pd.read_sql( soil_query, dbconn )
                if soil_df.empty:
                    continue
                #soil_row = soils_df.loc[soils_df[f'{soil_key}'] == i]
                #initialize .apsim xml
                apsim_xml = Element( 'folder' )
                apsim_xml.set( 'version', '36' )
                apsim_xml.set( 'creator', 'C-CHANGE Foresite' )
                apsim_xml.set( 'name', county_name )
                sim = SubElement( apsim_xml, 'simulation' )
                sim.set( 'name', f'{county_name} {field_id}' )
                
                #set met file
                metfile = SubElement( sim, 'metfile' )
                metfile.set( 'name', f'{county_name}' )
                filename = SubElement( metfile, 'filename' )
                filename.set( 'name', 'filename' )
                filename.set( 'input', 'yes' )
                filename.text = met_path

                #set clock
                clock = SubElement( sim, 'clock' )
                clock_start = SubElement( clock, 'start_date' )
                clock_start.set( 'type', 'date' )
                clock_start.set( 'description', 'Enter the start date of the simulation' )
                clock_start.text = start_date
                clock_end = SubElement( clock, 'end_date' )
                clock_end.set( 'type', 'date' )
                clock_end.set( 'description', 'Enter the end date of the simulation' )
                clock_end.text = end_date
                sumfile = SubElement( sim, 'summaryfile' )
                area = SubElement( sim, 'area' )
                area.set( 'name', 'paddock' )

                # add soil xml
                soil = apsim.Soil( soil_df, SWIM = False, SaxtonRawls = False )
                area.append( soil.soil_xml() )
                ### surface om
                surfom_xml = apsim.init_surfaceOM( 'maize', 'maize', 3500, 65, 0.0 )
                area.append( surfom_xml )
                ### fertilizer
                fert_xml = SubElement( area, 'fertiliser' )

                ### crops
                crop_xml = SubElement( area, 'maize' )
                crop_xml = SubElement( area, 'soybean' )
                crop_xml = SubElement( area, 'wheat' )

                ### output file
                outvars = [
                    'title',
                    'dd/mm/yyyy as date',
                    'day',
                    'year',
                    'soybean.yield as soybean_yield',
                    'maize.yield as maize_yield',
                    'soybean.biomass as soybean_biomass',
                    'maize.biomass as maize_biomass',
                    'corn_buac',
                    'soy_buac',
                    'fertiliser',
                    'surfaceom_c',
                    'subsurface_drain',
                    'subsurface_drain_no3',
                    'leach_no3'
                ]
                output_xml = apsim.set_output_variables( f'{county_name}_{field_id}_{soil_id}.out', outvars )
                area.append( output_xml )

                graph_no3 = [
                    'Cumulative subsurface_drain',
                    'Cumulative subsurface_drain_no3',
                    'Cumulative leach_no3'
                ]
                graph_yield = [
                    'soybean_yield',
                    'maize_yield',
                    'soybean_biomass',
                    'maize_biomass',
                    'soy_buac',
                    'corn_buac'
                ]
                graph_all = [
                    'soybean_yield',
                    'maize_yield',
                    'soybean_biomass',
                    'maize_biomass',
                    'corn_buac',
                    'soy_buac',
                    'fertiliser',
                    'surfaceom_c',
                    'subsurface_drain',
                    'subsurface_drain_no3',
                    'leach_no3' 
                ]

                output_xml.append( apsim.add_xy_graph( 'Date', graph_no3, 'no3' ) )
                output_xml.append( apsim.add_xy_graph( 'Date', graph_yield, 'yield' ) )
                output_xml.append( apsim.add_xy_graph( 'Date', graph_all, 'all outputs' ) )

                op_man = apsim.OpManager()
                op_man.add_empty_manager()
                if rotation == 'cfs':
                    add_management_year(op_man, cfs_mgmt, 2016)
                    add_management_year(op_man, sfc_mgmt, 2017)
                    add_management_year(op_man, cfs_mgmt, 2018)
                elif rotation == 'sfc':
                    add_management_year(op_man, sfc_mgmt, 2016)
                    add_management_year(op_man, cfs_mgmt, 2017)
                    add_management_year(op_man, sfc_mgmt, 2018)
                elif rotation == 'cc':
                    add_management_year(op_man, cc_mgmt, 2016)
                    add_management_year(op_man, cc_mgmt, 2017)
                    add_management_year(op_man, cc_mgmt, 2018)
                else:
                    continue
                area.append( op_man.man_xml )
                outfile = f'apsim_files/{county_name}_{field_id}_{soil_id}.apsim'
                ### management data
                tree = ElementTree()
                tree._setroot( apsim_xml )
                tree.write( outfile )
                sim_count += 1
                if (sim_count % 5 == 0):
                    print(f'Finished with {sim_count} files.')
            except:
                print(f'File creation failed for APSIM run {sim_count}')
                sim_count +=1
                continue

def create_mukey_runs(soils_list, dbconn, rotation, county_name, fips, start_year=2016, end_year=2018, swim = False, saxton=True):
    if not os.path.exists(f'apsim_files/{county_name}'):
        os.makedirs(f'apsim_files/{county_name}')
    start_date = f'01/01/{start_year}'
    end_date = f'31/12/{end_year}'
    #save rotation for clukey to crops list
    #loop through field keys e.g., clukeys
    total_sims = len(soils_list)
    sim_count = 0
    met_name = f"{county_name}.met"
    met_path = f"met_files/{met_name}"
    for i in soils_list:
        try:
            soil_id = i
            soil_query = '''select * from api.get_soil_properties( array[{}]::text[] )'''.format( i )
            soil_df = pd.read_sql( soil_query, dbconn )
            if soil_df.empty:
                print(f'Soil {i} not found')
                continue
            #soil_row = soils_df.loc[soils_df[f'{soil_key}'] == i]
            #initialize .apsim xml
            apsim_xml = Element( 'folder' )
            apsim_xml.set( 'version', '36' )
            apsim_xml.set( 'creator', 'C-CHANGE Foresite' )
            apsim_xml.set( 'name', county_name )
            sim = SubElement( apsim_xml, 'simulation' )
            sim.set( 'name', f'County_{county_name}_fips_{fips}_mukey_{soil_id}_rot_{rotation}_sim' )
            
            #set met file
            metfile = SubElement( sim, 'metfile' )
            metfile.set( 'name', f'{county_name}' )
            filename = SubElement( metfile, 'filename' )
            filename.set( 'name', 'filename' )
            filename.set( 'input', 'yes' )
            filename.text = met_path

            #set clock
            clock = SubElement( sim, 'clock' )
            clock_start = SubElement( clock, 'start_date' )
            clock_start.set( 'type', 'date' )
            clock_start.set( 'description', 'Enter the start date of the simulation' )
            clock_start.text = start_date
            clock_end = SubElement( clock, 'end_date' )
            clock_end.set( 'type', 'date' )
            clock_end.set( 'description', 'Enter the end date of the simulation' )
            clock_end.text = end_date
            sumfile = SubElement( sim, 'summaryfile' )
            area = SubElement( sim, 'area' )
            area.set( 'name', 'paddock' )

            # add soil xml
            soil = apsim.Soil( soil_df, swim, saxton )
            area.append( soil.soil_xml() )
            ### surface om
            if rotation == 'cfs':
                surfom_xml = apsim.init_surfaceOM( 'soybean', 'soybean', 1250, 27, 0.0 )
            else:
                surfom_xml = apsim.init_surfaceOM( 'maize', 'maize', 3500, 65, 0.0 )
            area.append( surfom_xml )
            ### fertilizer
            fert_xml = SubElement( area, 'fertiliser' )

            ### crops
            crop_xml = SubElement( area, 'maize' )
            crop_xml = SubElement( area, 'soybean' )
            #crop_xml = SubElement( area, 'wheat' )

            ### output file
            outvars = [
                'title',
                'dd/mm/yyyy as date',
                'day',
                'year',
                'soybean.yield as soybean_yield',
                'maize.yield as maize_yield',
                'soybean.biomass as soybean_biomass',
                'maize.biomass as maize_biomass',
                'corn_buac',
                'soy_buac',
                'fertiliser',
                'surfaceom_c',
                'subsurface_drain',
                'subsurface_drain_no3',
                'leach_no3' ]
            output_xml = apsim.set_output_variables( f'County_{county_name}_fips_{fips}_mukey_{soil_id}_rot_{rotation}_sim.out', outvars )
            area.append( output_xml )
            graph_no3 = [
                'Cumulative subsurface_drain',
                'Cumulative subsurface_drain_no3',
                'Cumulative leach_no3'
            ]
            graph_yield = [
                'soybean_yield',
                'maize_yield',
                'soybean_biomass',
                'maize_biomass',
                'soy_buac',
                'corn_buac'
            ]
            graph_all = [
                'soybean_yield',
                'maize_yield',
                'soybean_biomass',
                'maize_biomass',
                'corn_buac',
                'soy_buac',
                'fertiliser',
                'surfaceom_c',
                'subsurface_drain',
                'subsurface_drain_no3',
                'leach_no3' 
            ]

            output_xml.append( apsim.add_xy_graph( 'Date', graph_no3, 'no3' ) )
            output_xml.append( apsim.add_xy_graph( 'Date', graph_yield, 'yield' ) )
            output_xml.append( apsim.add_xy_graph( 'Date', graph_all, 'all outputs' ) )

            op_man = apsim.OpManager()
            op_man.add_empty_manager()
            if rotation == 'cfs':
                add_management_year(op_man, cfs_mgmt, 2016)
                add_management_year(op_man, sfc_mgmt, 2017)
                add_management_year(op_man, cfs_mgmt, 2018)
            elif rotation == 'sfc':
                add_management_year(op_man, sfc_mgmt, 2016)
                add_management_year(op_man, cfs_mgmt, 2017)
                add_management_year(op_man, sfc_mgmt, 2018)
            elif rotation == 'cc':
                add_management_year(op_man, cc_mgmt, 2016)
                add_management_year(op_man, cc_mgmt, 2017)
                add_management_year(op_man, cc_mgmt, 2018)
            else:
                continue
            
            area.append( op_man.man_xml )
            outfile = f'apsim_files/{county_name}/{county_name}_{soil_id}_{rotation}.apsim'
            ### management data
            tree = ElementTree()
            tree._setroot( apsim_xml )
            tree.write( outfile )
            sim_count += 1
            if (sim_count % 20 == 0):
                print(f'Finished with {sim_count} files.')
            if sim_count == total_sims:
                print('Finished! All files created!')
        except:
            print(f'File creation failed for APSIM run {sim_count} mukey {soil_id}')
            sim_count +=1
            continue

if __name__ == "__main__":
    soils_test_list = (1453495, 1453495)
    create_mukey_runs(soils_test_list, dbconn, 'sfc', 'Greene', 'IA073')
    create_mukey_runs(soils_test_list, dbconn, 'cc', 'Greene', 'IA073')
    create_mukey_runs(soils_test_list, dbconn, 'cfs', 'Greene', 'IA073')

################################################################################
# create directories for dumping .apsim and .met files
# if not os.path.exists( 'apsim_files' ):
#     os.makedirs( 'apsim_files' )
# if not os.path.exists( 'apsim_files/met_files' ):
#     os.makedirs( 'apsim_files/met_files' )

# # loop of tasks
# for idx,task in input_tasks.iterrows():
#     uuid = str( task[ 'uuid' ] )
#     mukey = task[ 'mukey' ]
#     fips = task[ 'fips' ]
#     lat = task[ 'wth_lat' ]
#     lon = task[ 'wth_lon' ]

#     print( 'Processing: ' + uuid )

#     # get soils data
#     soil_query = '''select * from
#         api.get_soil_properties( array[{}]::text[] )'''.format( mukey )
#     soil_df = pd.read_sql( soil_query, dbconn )
#     if soil_df.empty:
#         continue

#     # generate .met files
#     met_path = 'met_files/weather_{}.met'.format( fips )
#     if not os.path.exists( 'apsim_files/' + met_path ):
#         wth_obj = apsim.Weather().from_daymet( lat, lon, 1980, 2018 )
#         wth_obj.write_met_file( 'apsim_files/{}'.format( met_path ) )

#     # initialize .apsim xml
#     apsim_xml = Element( 'folder' )
#     apsim_xml.set( 'version', '36' )
#     apsim_xml.set( 'creator', 'Apsim_Wrapper' )
#     apsim_xml.set( 'name', 'S1' )
#     sim = SubElement( apsim_xml, 'simulation' )
#     sim.set( 'name', SIM_NAME )
#     metfile = SubElement( sim, 'metfile' )
#     metfile.set( 'name', 'foresite_weather' )
#     filename = SubElement( metfile, 'filename' )
#     filename.set( 'name', 'filename' )
#     filename.set( 'input', 'yes' )
#     filename.text = met_path
#     clock = SubElement( sim, 'clock' )
#     clock_start = SubElement( clock, 'start_date' )
#     clock_start.set( 'type', 'date' )
#     clock_start.set( 'description', 'Enter the start date of the simulation' )
#     clock_start.text = START_DATE
#     clock_end = SubElement( clock, 'end_date' )
#     clock_end.set( 'type', 'date' )
#     clock_end.set( 'description', 'Enter the end date of the simulation' )
#     clock_end.text = END_DATE
#     sumfile = SubElement( sim, 'summaryfile' )
#     area = SubElement( sim, 'area' )
#     area.set( 'name', 'paddock' )

#     # add soil xml
#     soil = apsim.Soil(
#         soil_df,
#         SWIM = False,
#         SaxtonRawls = False )

#     area.append( soil.soil_xml() )

#     ### surface om
#     surfom_xml = apsim.init_surfaceOM( 'maize', 'maize', 3500, 65, 0.0 )
#     area.append( surfom_xml )

#     ### fertilizer
#     fert_xml = SubElement( area, 'fertiliser' )

#     ### crops
#     crop_xml = SubElement( area, 'maize' )
#     crop_xml = SubElement( area, 'soybean' )
#     crop_xml = SubElement( area, 'wheat' )

#     ### output file
#     outvars = [
#         'dd/mm/yyyy as Date', 'day', 'year',
#         'yield', 'biomass', 'fertiliser',
#         'surfaceom_c', 'subsurface_drain',
#         'subsurface_drain_no3', 'leach_no3',
#         'corn_buac', 'soy_buac' ]
#     output_xml = apsim.set_output_variables( uuid + '.out', outvars )
#     area.append( output_xml )

#     graph_no3 = [
#         'Cumulative subsurface_drain',
#         'Cumulative subsurface_drain_no3',
#         'Cumulative leach_no3'
#     ]
#     graph_yield = [
#         'yield',
#         'biomass',
#         'corn_buac'
#     ]
#     graph_all = [
#         'yield', 'biomass', 'fertiliser',
#         'surfaceom_c', 'Cumulative subsurface_drain',
#         'Cumulative subsurface_drain_no3',
#         'Cumulative leach_no3', 'corn_buac',
#         'soy_buac'
#     ]

#     output_xml.append( apsim.add_xy_graph( 'Date', graph_no3, 'no3' ) )
#     output_xml.append( apsim.add_xy_graph( 'Date', graph_yield, 'yield' ) )
#     output_xml.append( apsim.add_xy_graph( 'Date', graph_all, 'all outputs' ) )

#     op_man = apsim.OpManager()
#     op_man.add_empty_manager()

#     add_management_year( op_man, spin_up_corn, 2016 )
#     add_management_year( op_man, spin_up_soybean, 2017 )
#     add_management_year( op_man, task, 2018 )

#     area.append( op_man.man_xml )

#     outfile = 'apsim_files/{}.apsim'.format( uuid )
#     print( outfile )
#     ### management data
#     tree = ElementTree()
#     tree._setroot( apsim_xml )
#     tree.write( outfile )
