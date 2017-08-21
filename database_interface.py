# Copyright 2017. All rights reserved. See AUTHORS.txt
# Licensed under the Apache License, Version 2.0 which is in LICENSE.txt
"""
Provides several functions to work with the SWITCH database.

Many are ad-hoc functions for interactive exploration of the data.

To Do:
Push the cleaned and validated data into postgresql.
Assign plants to load zones in postgresql.
Aggregate similar plants within each load zone in postgresql to reduce the
dataset size for the model.

"""

import os, sys
import pandas as pd
import numpy as np
import getpass
from utils import connect_to_db_and_run_query, append_historic_output_to_csv, connect_to_db_and_push_df
from IPython import embed
from ggplot import *

coal_codes = ['ANT','BIT','LIG','SGC','SUB','WC','RC']
outputs_directory = 'processed_data'
# Disable false positive warnings from pandas
pd.options.mode.chained_assignment = None


def pull_generation_projects_data():
    print "Reading in current generation projects data from database..."
    query = "SELECT * \
            FROM generation_plant JOIN generation_plant_existing_and_planned \
            USING (generation_plant_id) \
            WHERE generation_plant_existing_and_planned_scenario_id = 1 "#AND full_load_heat_rate > 0"
    db_gens = connect_to_db_and_run_query(query=query, database='switch_wecc')
    print "======="year
    print "Read in {} projects from the database, with {:.0f} GW of capacity".format(
        len(db_gens), db_gens['capacity'].sum()/1000.0)
    thermal_db_gens = db_gens[db_gens['full_load_heat_rate'] > 0]
    print "Weighted average of heat rate: {:.3f} MMBTU/MWh".format(
        thermal_db_gens['capacity'].dot(thermal_db_gens['full_load_heat_rate'])/thermal_db_gens['capacity'].sum())
    print "======="
    return db_gens

def explore_heat_rates():
    db_gen_projects = pull_generation_projects_data().rename(columns={'name':'Plant Name', 'gen_tech':'Prime Mover'})
    db_gen_projects.loc[:,'Prime Mover'].replace(
        {
        'Coal_Steam_Turbine':'ST',
        'Gas_Steam_Turbine':'ST',
        'Gas_Combustion_Turbine':'GT',
        'Gas_Combustion_Turbine_Cogen':'GT',
        'CCGT':'CC',
        'DistillateFuelOil_Combustion_Turbine':'GT',
        'DistillateFuelOil_Internal_Combustion_Engine':'IC',
        'Geothermal':'ST',
        'Gas_Internal_Combustion_Engine':'IC',
        'Bio_Gas_Internal_Combustion_Engine':'IC',
        'Bio_Gas_Steam_Turbine':'ST'
        },
        inplace=True)
    eia_gen_projects = filter_projects_by_region_id(13)

    df = pd.merge(db_gen_projects, eia_gen_projects,
        on=['Plant Name','Prime Mover'], how='left').loc[:,[
        'Plant Name','gen_tech','energy_source','full_load_heat_rate',
        'Best Heat Rate','Prime Mover','Energy Source','Energy Source 2','Operating Year']]
    df = df[df['full_load_heat_rate']>0]

    print "\nPrinting intersection of DB and EIA generation projects that have a specified heat rate to heat_rate_comparison.tab"
    
    fpath = os.path.join('processed_data','heat_rate_comparison.tab')
    with open(fpath, 'w') as outfile:
        df.to_csv(outfile, sep='\t', header=True, index=False)

    return df

def filter_projects_by_region_id(region_id, year, host='localhost', area=0.5):
    """
    Filters generation project data by NERC Region and assigns Regions to rows
    that do not have one, according to their County and State. Rows will get
    assigned to a Region is more than a certain percentage of the area of the
    county it belongs to intersects with the specified Region.

    Returns a DataFrame with the filtered data.

    """

    state_dict = {
        'Alabama':'AL',
        'Alaska':'AK',
        'Arizona':'AZ',
        'Arkansas':'AR',
        'California':'CA',
        'Colorado':'CO',
        'Connecticut':'CT',
        'Delaware':'DE',
        'Florida':'FL',
        'Georgia':'GA',
        'Hawaii':'HI',
        'Idaho':'ID',
        'Illinois':'IL',
        'Indiana':'IN',
        'Iowa':'IA',
        'Kansas':'KS',
        'Kentucky':'KY',
        'Louisiana':'LA',
        'Maine':'ME',
        'Maryland':'MD',
        'Massachusetts':'MA',
        'Michigan':'MI',
        'Minnesota':'MN',
        'Mississippi':'MS',
        'Missouri':'MO',
        'Montana':'MT',
        'Nebraska':'NE',
        'Nevada':'NV',
        'New Hampshire':'NH',
        'New Jersey':'NJ',
        'New Mexico':'NM',
        'New York':'NY',
        'North Carolina':'NC',
        'North Dakota':'ND',
        'Ohio':'OH',
        'Oklahoma':'OK',
        'Oregon':'OR',
        'Pennsylvania':'PA',
        'Rhode Island':'RI',
        'South Carolina':'SC',
        'South Dakota':'SD',
        'Tennessee':'TN',
        'Texas':'TX',
        'Utah':'UT',
        'Vermont':'VT',
        'Virginia':'VA',
        'Washington':'WA',
        'West Virginia':'WV',
        'Wisconsin':'WI',
        'Wyoming':'WY'
    }

    print "Getting region name from database..."
    query = "SELECT regionabr FROM ventyx_nerc_reg_region WHERE gid={}".format(
        region_id)
    region_name = connect_to_db_and_run_query(query=query,
        database='switch_gis', host=host)['regionabr'][0]
    counties_path = os.path.join('other_data', '{}_counties.tab'.format(region_name))
    
    if not os.path.exists(counties_path):
        # assign county if (area)% or more of its area falls in the region
        query = "SELECT name, state\
                 FROM ventyx_nerc_reg_region regions CROSS JOIN us_counties cts\
                 JOIN (SELECT DISTINCT state, state_fips FROM us_states) sts \
                 ON (sts.state_fips=cts.statefp) \
                 WHERE regions.gid={} AND\
                 ST_Area(ST_Intersection(cts.the_geom, regions.the_geom))/\
                 ST_Area(cts.the_geom)>={}".format(region_id, area)
        print "\nGetting counties and states for the region from database..."
        region_counties = pd.DataFrame(connect_to_db_and_run_query(query=query,
            database='switch_gis', host=host)).rename(columns={'name':'County','state':'State'})
        region_counties.replace(state_dict, inplace=True)
        region_counties.to_csv(counties_path, sep='\t', index=False)
    else:
        print "Reading counties from .tab file..."
        region_counties = pd.read_csv(counties_path, sep='\t', index_col=None)

    generators = pd.read_csv(
        os.path.join('processed_data','generation_projects_{}.tab'.format(year)), sep='\t')
    generators.loc[:,'County'] = generators['County'].map(lambda c: str(c).title())

    print "\nRead in data for {} generators, of which:".format(len(generators))
    print "--{} are existing".format(len(generators[generators['Operational Status']=='Operable']))
    print "--{} are proposed".format(len(generators[generators['Operational Status']=='Proposed']))

    generators_with_assigned_region = generators.loc[generators['Nerc Region'] == region_name]
    generators = generators[generators['Nerc Region'].isnull()]
    generators_without_assigned_region = pd.merge(generators, region_counties, how='inner', on=['County','State'])
    generators = pd.concat([
        generators_with_assigned_region,
        generators_without_assigned_region],
        axis=0)
    generators.replace(
            to_replace={'Energy Source':coal_codes, 'Energy Source 2':coal_codes,
            'Energy Source 3':coal_codes}, value='COAL', inplace=True)
    generators_columns = list(generators.columns)

    existing_gens = generators[generators['Operational Status']=='Operable']
    proposed_gens = generators[generators['Operational Status']=='Proposed']

    print "======="
    print "Filtered to {} projects in the {} region, of which:".format(
        len(generators), region_name)
    print "--{} are existing with {:.0f} GW of capacity".format(
        len(existing_gens), existing_gens['Nameplate Capacity (MW)'].sum()/1000.0)
    print "--{} are proposed with {:.0f} GW of capacity".format(
        len(proposed_gens), proposed_gens['Nameplate Capacity (MW)'].sum()/1000.0)
    print "======="

    return generators


def assign_heat_rates_to_projects(generators, year):
    fuels = {
        'LFG':'Bio_Gas',
        'OBG':'Bio_Gas',
        'AB':'Bio_Solid',
        'BLQ':'Bio_Liquid',
        'NG':'Gas',
        'OG':'Gas',
        'PG':'Gas',
        'DFO':'DistillateFuelOil',
        'JF':'ResidualFuelOil',
        'COAL':'Coal',
        'GEO':'Geothermal',
        'NUC':'Uranium',
        'PC':'Coal',
        'SUN':'Solar',
        'WDL':'Bio_Liquid',
        'WDS':'Bio_Solid',
        'MSW':'Bio_Solid',
        'PUR':'Purchased_Steam',
        'WH':'Waste_Heat',
        'OTH':'Other',
        'WAT':'Water',
        'MWH':'Electricity',
        'WND':'Wind'
    }
    generators = generators.replace({'Energy Source':fuels})

    existing_gens = generators[generators['Operational Status']=='Operable']
    print "-------------------------------------"
    print "There are {} existing thermal projects that sum up to {:.1f} GW.".format(
        len(existing_gens[existing_gens['Prime Mover'].isin(['CC','GT','IC','ST'])]),
        existing_gens[existing_gens['Prime Mover'].isin(['CC','GT','IC','ST'])][
            'Nameplate Capacity (MW)'].sum()/1000)
    heat_rate_data = pd.read_csv(
        os.path.join('processed_data','historic_heat_rates_WIDE.tab'), sep='\t').rename(
        columns={'Plant Code':'EIA Plant Code'})
    heat_rate_data = heat_rate_data[heat_rate_data['Year']==year]
    heat_rate_data = heat_rate_data.replace({'Energy Source':fuels})
    thermal_gens = pd.merge(
        existing_gens, heat_rate_data[['EIA Plant Code','Prime Mover','Energy Source','Best Heat Rate']],
        how='left', suffixes=('',''),
        on=['EIA Plant Code','Prime Mover','Energy Source']).drop_duplicates()

    thermal_gens = thermal_gens[thermal_gens['Prime Mover'].isin(['CC','GT','IC','ST'])]

    # Replace null and unrealistic heat rates by average values per technology,
    # fuel, and vintage. Also, set HR of top and bottom .5% to max and min
    null_heat_rates = thermal_gens['Best Heat Rate'].isnull()
    unrealistic_heat_rates = (((thermal_gens['Energy Source'] == 'Coal') &
            (thermal_gens['Best Heat Rate'] < 8.607)) |
        ((thermal_gens['Energy Source'] != 'Coal') &
            (thermal_gens['Best Heat Rate'] < 6.711)))
    print "{} generators don't have heat rate data specified ({:.1f} GW of capacity)".format(
        len(thermal_gens[null_heat_rates]), thermal_gens[null_heat_rates]['Nameplate Capacity (MW)'].sum()/1000.0)
    print "{} generators have better heat rate than the best historical records ({} GW of capacity)".format(
        len(thermal_gens[unrealistic_heat_rates]), thermal_gens[unrealistic_heat_rates]['Nameplate Capacity (MW)'].sum()/1000.0)
    thermal_gens_w_hr = thermal_gens[~null_heat_rates & ~unrealistic_heat_rates]
    thermal_gens_wo_hr = thermal_gens[null_heat_rates | unrealistic_heat_rates]

    # Print fuels and technologies with missing HR to console

    # for fuel in thermal_gens_wo_hr['Energy Source'].unique():
    #     print "{} of these use {} as their fuel".format(
    #         len(thermal_gens_wo_hr[thermal_gens_wo_hr['Energy Source']==fuel]),fuel)
    #     print "Technologies:"
    #     for prime_mover in thermal_gens_wo_hr[thermal_gens_wo_hr['Energy Source']==fuel]['Prime Mover'].unique():
    #         print "\t{} use {}".format(
    #             len(thermal_gens_wo_hr[(thermal_gens_wo_hr['Energy Source']==fuel) &
    #                 (thermal_gens_wo_hr['Prime Mover']==prime_mover)]),prime_mover)
    
    print "-------------------------------------"
    print "Assigning max/min heat rates per technology and fuel to top .5% / bottom .5%, respectively:"
    n_outliers = int(len(thermal_gens_w_hr)*0.008)
    thermal_gens_w_hr = thermal_gens_w_hr.sort_values('Best Heat Rate')
    min_hr = thermal_gens_w_hr.loc[thermal_gens_w_hr.index[n_outliers],'Best Heat Rate']
    max_hr = thermal_gens_w_hr.loc[thermal_gens_w_hr.index[-1-n_outliers],'Best Heat Rate']
    print "(Total capacity of these plants is {:.1f} GW)".format(
        thermal_gens_w_hr[thermal_gens_w_hr['Best Heat Rate'] < min_hr]['Nameplate Capacity (MW)'].sum()/1000.0 +
        thermal_gens_w_hr[thermal_gens_w_hr['Best Heat Rate'] > max_hr]['Nameplate Capacity (MW)'].sum()/1000.0)
    print "Minimum heat rate is {:.3f}".format(min_hr)
    print "Maximum heat rate is {:.3f}".format(max_hr)
    for i in range(n_outliers):
        thermal_gens_w_hr.loc[thermal_gens_w_hr.index[i],'Best Heat Rate'] = min_hr
        thermal_gens_w_hr.loc[thermal_gens_w_hr.index[-1-i],'Best Heat Rate'] = max_hr


    def calculate_avg_heat_rate(thermal_gens_df, prime_mover, energy_source, vintage, window=2):
        similar_generators = thermal_gens_df[
            (thermal_gens_df['Prime Mover']==prime_mover) &
            (thermal_gens_df['Energy Source']==energy_source) &
            (thermal_gens_df['Operating Year']>=vintage-window) &
            (thermal_gens_df['Operating Year']<=vintage+window)]
        while len(similar_generators) < 4:
            window += 2
            similar_generators = thermal_gens_df[
                (thermal_gens_df['Prime Mover']==prime_mover) &
                (thermal_gens_df['Energy Source']==energy_source) &
                (thermal_gens_df['Operating Year']>=vintage-window) &
                (thermal_gens_df['Operating Year']<=vintage+window)]
            # Gens span from 1925 to 2015, so a window of 90 years is the maximum
            if window >= 90:
                break
        if len(similar_generators) > 0:
            return similar_generators['Best Heat Rate'].mean()
        else:
            # If no other similar projects exist, return average of technology
            return thermal_gens_df[thermal_gens_df['Prime Mover']==prime_mover]['Best Heat Rate'].mean()


    print "-------------------------------------"
    print "Assigning average heat rates per technology, fuel, and vintage to projects w/o heat rate..."
    for idx in thermal_gens_wo_hr.index:
        pm = thermal_gens_wo_hr.loc[idx,'Prime Mover']
        es = thermal_gens_wo_hr.loc[idx,'Energy Source']
        v = thermal_gens_wo_hr.loc[idx,'Operating Year']
        #print "{}\t{}\t{}\t{}".format(pm,es,v,calculate_avg_heat_rate(thermal_gens_w_hr, pm, es, v))
        thermal_gens_wo_hr.loc[idx,'Best Heat Rate'] = calculate_avg_heat_rate(
            thermal_gens_w_hr, pm, es, v)

    thermal_gens = pd.concat([thermal_gens_w_hr, thermal_gens_wo_hr], axis=0)
    existing_gens = pd.merge(existing_gens, thermal_gens, on=list(existing_gens.columns), how='left')


    # Plot histograms for resulting heat rates per technology and fuel
    thermal_gens["Technology"] = thermal_gens["Energy Source"].map(str) + ' ' + thermal_gens["Prime Mover"]
    p = ggplot(aes(x='Best Heat Rate',fill='Technology'), data=thermal_gens) + geom_histogram(binwidth=0.5) + facet_wrap("Technology")  + ylim(0,30)
    p.save(os.path.join(outputs_directory,'heat_rate_distributions.pdf'))

    proposed_gens = generators[generators['Operational Status']=='Proposed']
    thermal_proposed_gens = proposed_gens[proposed_gens['Prime Mover'].isin(['CC','GT','IC','ST'])]
    other_proposed_gens = proposed_gens[~proposed_gens['Prime Mover'].isin(['CC','GT','IC','ST'])]
    print "There are {} proposed thermal projects that sum up to {:.2f} GW.".format(
        len(thermal_proposed_gens), thermal_proposed_gens['Nameplate Capacity (MW)'].sum()/1000)
    print "Assigning average heat rate of technology and fuel of most recent years..."
    for idx in thermal_proposed_gens.index:
        pm = thermal_proposed_gens.loc[idx,'Prime Mover']
        es = thermal_proposed_gens.loc[idx,'Energy Source']
        #print "{}\t{}\t{}\t{}".format(pm,es,v,calculate_avg_heat_rate(thermal_gens_w_hr, pm, es, v))
        thermal_proposed_gens.loc[idx,'Best Heat Rate'] = calculate_avg_heat_rate(
            thermal_gens_w_hr, pm, es, year)

    other_proposed_gens['Best Heat Rate'] = float('nan')
    proposed_gens = pd.concat([thermal_proposed_gens,other_proposed_gens], axis=0)

    return pd.concat([existing_gens, proposed_gens], axis=0)


def finish_project_processing(year):
    generators = filter_projects_by_region_id(13, year)
    generators = assign_heat_rates_to_projects(generators, year)
    existing_gens = generators[generators['Operational Status']=='Operable']
    proposed_gens = generators[generators['Operational Status']=='Proposed']

    fname = 'existing_generation_projects_{}.tab'.format(year)
    with open(os.path.join(outputs_directory, fname),'w') as f:
        existing_gens.to_csv(f, sep='\t', encoding='utf-8', index=False)

    uprates = pd.DataFrame()
    new_gens = pd.DataFrame()
    for idx in proposed_gens.index:
        pc = proposed_gens.loc[idx,'EIA Plant Code']
        pm = proposed_gens.loc[idx,'Prime Mover']
        es = proposed_gens.loc[idx,'Energy Source']
        existing_units_for_proposed_gen = existing_gens[
        (existing_gens['EIA Plant Code'] == pc) &
        (existing_gens['Prime Mover'] == pm) &
        (existing_gens['Energy Source'] == es)]
        if len(existing_units_for_proposed_gen) == 0:
            new_gens = pd.concat([new_gens, pd.DataFrame(proposed_gens.loc[idx,:]).T], axis=0)
        elif len(existing_units_for_proposed_gen) == 1:
            uprates = pd.concat([uprates, pd.DataFrame(proposed_gens.loc[idx,:]).T], axis=0)
        else:
            print "There is more than one option for uprating plant id {}, prime mover {} and energy source {}".format(int(pc), pm, es)

    fname = 'new_generation_projects_{}.tab'.format(year)
    with open(os.path.join(outputs_directory, fname),'w') as f:
        new_gens.to_csv(f, sep='\t', encoding='utf-8', index=False)

    fname = 'uprates_to_generation_projects_{}.tab'.format(year)
    with open(os.path.join(outputs_directory, fname),'w') as f:
        uprates.to_csv(f, sep='\t', encoding='utf-8', index=False)


def upload_generation_projects(year):

    user = getpass.getpass('Enter username for the database:')
    password = getpass.getpass('Enter database password for user {}:'.format(user))

    def read_output_csv(fname):
        try:
            return pd.read_csv(os.path.join(outputs_directory,fname), sep='\t', index_col=None)
        except:
            print "Failed to read file {}. It will be considered to be empty.".format(fname)
            return None

    existing_gens = read_output_csv('existing_generation_projects_{}.tab'.format(year))
    new_gens = read_output_csv('new_generation_projects_{}.tab'.format(year))
    uprates = read_output_csv('uprates_to_generation_projects_{}.tab'.format(year))
    if uprates is not None:
        print "Read data for {} existing projects, {} new projects, and {} uprates".format(
            len(existing_gens), len(new_gens), len(uprates))
        print "Existing capacity: {:.2f} GW".format(existing_gens['Nameplate Capacity (MW)'].sum()/1000.0)
        print "Proposed capacity: {:.2f} GW".format(new_gens['Nameplate Capacity (MW)'].sum()/1000.0)
        print "Capacity uprates: {:.2f} GW".format(uprates['Nameplate Capacity (MW)'].sum()/1000.0)
    else:
        print "Read data for {} existing projects and {} new projects".format(
            len(existing_gens), len(new_gens))
        print "Existing capacity: {:.2f} GW".format(existing_gens['Nameplate Capacity (MW)'].sum()/1000.0)
        print "Proposed capacity: {:.2f} GW".format(new_gens['Nameplate Capacity (MW)'].sum()/1000.0)

    generators = pd.concat([existing_gens, new_gens], axis=0)

    ignore_energy_sources = ['Purchased_Steam','Electricity']

    print ("Dropping projects that use Batteries or Purchased Steam, since these"
    " are not modeled in Switch, totalizing {:.2f} GW of capacity").format(
        generators[generators['Energy Source'].isin(
            ignore_energy_sources)]['Nameplate Capacity (MW)'].sum()/1000.0)
    print "Replacing 'Other' for 'Gas' as energy source for {:.2f} GW of capacity".format(
        generators[generators['Energy Source'] == 'Other'][
            'Nameplate Capacity (MW)'].sum()/1000.0)
    generators.drop(generators[generators['Energy Source'].isin(
            ignore_energy_sources)].index, inplace=True)
    generators.replace({'Energy Source':{'Other':'Gas'}}, inplace=True)


    def wavg(group, avg_name, weight_name):
        """
        http://stackoverflow.com/questions/10951341/pandas-dataframe-aggregate-function-using-multiple-columns
        """
        d = group[avg_name]
        w = group[weight_name]
        try:
            return (d * w).sum() / w.sum()
        except ZeroDivisionError:
            return d.mean()

    index_cols = ['EIA Plant Code','Prime Mover','Energy Source']
    print "Calculating capacity-weighted average heat rates per plant, technology and energy source..."
    generators = pd.merge(generators,
        pd.DataFrame(generators.groupby(index_cols).apply(wavg,'Best Heat Rate',
            'Nameplate Capacity (MW)')).reset_index().replace(0,float('nan')),
        how='right',
        on=index_cols).drop('Best Heat Rate', axis=1)

    print "Calculating maximum capacity limits per plant, technology and energy source..."
    gb = generators.groupby(index_cols)
    agg_generators = gb.agg({col:sum if col == 'Nameplate Capacity (MW)' else 'max'
                                    for col in generators.columns}).rename(columns=
                                    {'Nameplate Capacity (MW)':'capacity_limit_mw'})
    generators = pd.merge(generators, agg_generators[index_cols+['capacity_limit_mw']],
        on=index_cols, how='right')

    print "Assigning baseload, variable and cogen flags..."
    generators.loc[:,'is_baseload'] = np.where(generators['Energy Source'].isin(
        ['Nuclear','Coal','Geothermal']),True,False)
    generators.loc[:,'is_variable'] = np.where(generators['Prime Mover'].isin(
        ['HY','PV','WT']),True,False)
    generators.loc[:,'is_cogen'] = np.where(generators['Cogen'] == 'Y',True,False)

    database_column_renaming_dict = {
        'EIA Plant Code':'eia_plant_code',
        'Plant Name':'name',
        'Prime Mover':'gen_tech',
        'Energy Source':'energy_source',
        0:'full_load_heat_rate',
        'Operating Year':'build_year',
        'Nameplate Capacity (MW)':'capacity'
        }

    generators.rename(columns=database_column_renaming_dict, inplace=True)

    generators.replace(' ',float('nan'), inplace=True)

    carry_on = getpass.getpass('WARNING: In order to push projects into the DB,'
        'all projects currently in the generation_plant table that are'
        'not present in the generation_plant_scenario_member table will be'
        'removed. Continue? [y/n]')
    if carry_on not in ['y','n']:
        carry_on = getpass.getpass('WARNING: In order to push projects into the DB,'
        'all projects currently in the generation_plant table that are'
        'not present in the generation_plant_scenario_member table will be'
        'removed. Continue? [y/n]')
    elif carry_on == 'n':
        sys.exit()

    print "\n-----------------------------"
    print "Pushing generation plants to the DB:\n"

    # Make sure the "switch" schema is on the search path

    # Drop NOT NULL constraint for load_zone_id & max_age cols to avoid raising error
    query = 'ALTER TABLE "generation_plant" ALTER "load_zone_id" DROP NOT NULL;'
    connect_to_db_and_run_query(query,
        database='switch_wecc', user=user, password=password, quiet=True)
    query = 'ALTER TABLE "generation_plant" ALTER "max_age" DROP NOT NULL;'
    connect_to_db_and_run_query(query,
        database='switch_wecc', user=user, password=password, quiet=True)

    # First, delete previously stored projects for the EIA scenario id
    gen_scenario_id = 2.0

    query = 'DELETE FROM hydro_historical_monthly_capacity_factors\
        WHERE hydro_simple_scenario_id = {}'.format(gen_scenario_id)
    connect_to_db_and_run_query(query,
            database='switch_wecc', user=user, password=password, quiet=True)

    query = 'DELETE FROM generation_plant_scenario_member\
        WHERE generation_plant_scenario_id = {}'.format(gen_scenario_id)
    connect_to_db_and_run_query(query,
            database='switch_wecc', user=user, password=password, quiet=True)

    query = 'DELETE FROM generation_plant_cost\
        WHERE generation_plant_cost_scenario_id = {}'.format(gen_scenario_id)
    connect_to_db_and_run_query(query,
            database='switch_wecc', user=user, password=password, quiet=True)

    query = 'DELETE FROM generation_plant_existing_and_planned\
        WHERE generation_plant_existing_and_planned_scenario_id = {}'.format(gen_scenario_id)
    connect_to_db_and_run_query(query,
            database='switch_wecc', user=user, password=password, quiet=True)

    # It is necessary to temporarily disable triggers when deleting from
    # generation_plant table, because of multiple fkey constraints
    query = 'SET session_replication_role = replica;\
            DELETE FROM generation_plant\
            WHERE generation_plant_id NOT IN\
            (SELECT generation_plant_id FROM generation_plant_scenario_member);\
            SET session_replication_role = DEFAULT;'
    connect_to_db_and_run_query(query,
            database='switch_wecc', user=user, password=password, quiet=True)

    print "Deleted previously stored projects for the EIA dataset (id 2). Pushing data..."

    query = 'SELECT last_value FROM generation_plant_id_seq'
    first_gen_id = connect_to_db_and_run_query(query,
        database='switch_wecc', user=user, password=password, quiet=True).iloc[0,0] + 1

    generators_to_db = generators[['name','gen_tech','capacity_limit_mw',
        'full_load_heat_rate','is_variable','is_baseload','is_cogen',
        'energy_source','eia_plant_code', 'Latitude','Longitude','County',
        'State']].drop_duplicates()

    connect_to_db_and_push_df(df=generators_to_db,
        col_formats=("(DEFAULT,%s,%s,NULL,NULL,%s,NULL,NULL,NULL,%s,NULL,NULL,"
            "NULL,%s,%s,%s,%s,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,%s,%s,%s,%s,%s,NULL)"),
        table='generation_plant',
        database='switch_wecc', user=user, password=password, quiet=True)
    print "Successfully pushed generation plants!"

    query = 'SELECT last_value FROM generation_plant_id_seq'
    last_gen_id = connect_to_db_and_run_query(query,
        database='switch_wecc', user=user, password=password, quiet=True).iloc[0,0]

    # Populate geometry column for GIS work
    query = "UPDATE generation_plant\
        SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)\
        WHERE longitude IS NOT NULL AND latitude IS NOT NULL AND\
        generation_plant_id BETWEEN {} AND {}".format(first_gen_id, last_gen_id)
    connect_to_db_and_run_query(query,
        database='switch_wecc', user=user, password=password, quiet=True)

    print "\nAssigning load zones..."
    query = "UPDATE generation_plant SET load_zone_id = z.load_zone_id\
        FROM load_zone z\
        WHERE ST_contains(boundary, geom) AND\
        generation_plant_id BETWEEN {} AND {}".format(first_gen_id, last_gen_id)
    connect_to_db_and_run_query(query,
        database='switch_wecc', user=user, password=password, quiet=True)
    n_plants_assigned_by_lat_long = connect_to_db_and_run_query("SELECT count(*)\
        FROM generation_plant WHERE load_zone_id IS NOT NULL AND\
        generation_plant_id BETWEEN {} AND {}".format(first_gen_id, last_gen_id),
        database='switch_wecc', user=user, password=password, quiet=True).iloc[0,0]
    print "--Assigned load zone according to lat & long to {} plants".format(
        n_plants_assigned_by_lat_long)

    query = "UPDATE generation_plant g SET load_zone_id = z.load_zone_id\
        FROM us_counties c\
        JOIN load_zone z ON ST_contains(z.boundary, ST_centroid(c.the_geom))\
        WHERE g.load_zone_id IS NULL AND g.state = c.state_name AND g.county = c.name\
        AND generation_plant_id BETWEEN {} AND {}".format(first_gen_id, last_gen_id)
    connect_to_db_and_run_query(query,
        database='switch_wecc', user=user, password=password, quiet=True)
    n_plants_assigned_by_county_state = connect_to_db_and_run_query("SELECT count(*)\
        FROM generation_plant WHERE load_zone_id IS NOT NULL AND\
        generation_plant_id BETWEEN {} AND {}".format(first_gen_id, last_gen_id),
        database='switch_wecc', user=user, password=password, quiet=True
        ).iloc[0,0] - n_plants_assigned_by_lat_long
    print "--Assigned load zone according to county & state to {} plants".format(
        n_plants_assigned_by_county_state)

    # Plants that are located outside of the WECC region boundary get assigned
    # to the nearest load zone, ONLY if they are located less than 100 miles
    # out of the boundary
    query = "UPDATE generation_plant AS g1 SET load_zone_id = lz1.load_zone_id\
        FROM load_zone lz1\
        WHERE g1.load_zone_id is NULL AND g1.geom IS NOT NULL\
        AND g1.generation_plant_id between {} AND {}\
        AND ST_Distance(g1.geom::geography,lz1.boundary::geography)/1609 < 100\
        AND ST_Distance(g1.geom::geography,lz1.boundary::geography)/1609 = \
        (SELECT min(ST_Distance(g2.geom::geography,lz2.boundary::geography)/1609)\
        FROM generation_plant g2\
        CROSS JOIN load_zone lz2\
        WHERE g2.load_zone_id is NULL AND g2.geom IS NOT NULL\
        AND g2.generation_plant_id = g1.generation_plant_id)".format(first_gen_id, last_gen_id)
    connect_to_db_and_run_query(query,
        database='switch_wecc', user=user, password=password, quiet=True)
    n_plants_assigned_to_nearest_lz = connect_to_db_and_run_query("SELECT count(*)\
        FROM generation_plant WHERE load_zone_id IS NOT NULL AND\
        generation_plant_id BETWEEN {} AND {}".format(first_gen_id, last_gen_id),
        database='switch_wecc', user=user, password=password, quiet=True
        ).iloc[0,0] - n_plants_assigned_by_lat_long - n_plants_assigned_by_county_state
    print "--Assigned load zone according to nearest load zone to {} plants".format(
        n_plants_assigned_to_nearest_lz)

    plants_wo_load_zone_count_and_cap = connect_to_db_and_run_query("SELECT count(*),\
        sum(capacity_limit_mw) FROM generation_plant WHERE load_zone_id IS NULL\
        AND generation_plant_id BETWEEN {} AND {}".format(first_gen_id, last_gen_id),
        database='switch_wecc', user=user, password=password, quiet=True)
    if plants_wo_load_zone_count_and_cap.iloc[0,0] > 0:
        print ("--WARNING: There are {:.0f} plants with a total of {:.2f} GW of capacity"
        " w/o an assigned load zone. These will be removed.").format(
        plants_wo_load_zone_count_and_cap.iloc[0,0],
        plants_wo_load_zone_count_and_cap.iloc[0,1]/1000.0)
        connect_to_db_and_run_query("DELETE FROM generation_plant\
            WHERE load_zone_id IS NULL AND generation_plant_id BETWEEN {}\
            AND {}".format(first_gen_id, last_gen_id),
            database='switch_wecc', user=user, password=password, quiet=True)

    # Assign default technology values
    print "\nAssigning default technology parameter values..."
    for param in ['max_age','forced_outage_rate','scheduled_outage_rate', 'variable_o_m']:
        query = "UPDATE generation_plant g SET {} = t.{}\
                FROM generation_plant_technologies t\
                WHERE g.energy_source = t.energy_source AND\
                g.gen_tech = t.gen_tech AND generation_plant_id BETWEEN {} AND\
                {}".format(param, param, first_gen_id, last_gen_id)
        connect_to_db_and_run_query(query,
            database='switch_wecc', user=user, password=password, quiet=True)
        print "--Assigned {}".format(param)

    # Manually assign maximum age for diablo canyon
    query = "UPDATE generation_plant SET max_age = 40 WHERE name = 'Diablo Canyon'"
    connect_to_db_and_run_query(query,
            database='switch_wecc', user=user, password=password, quiet=True)

    # Now, create scenario and assign ids for scenario #2
    # Get the actual list of ids in the table, since some rows were deleted
    # because no load zone could be assigned to those projects
    print "\nAssigning all individual plants to scenario id {}...".format(gen_scenario_id)
    query = 'SELECT generation_plant_id FROM generation_plant\
        WHERE generation_plant_id BETWEEN {} AND {}'.format(first_gen_id, last_gen_id)
    gen_plant_ids = connect_to_db_and_run_query(query,
                database='switch_wecc', user=user, password=password, quiet=True)
    gen_plant_ids['generation_plant_scenario_id'] = gen_scenario_id

    connect_to_db_and_push_df(df=gen_plant_ids[['generation_plant_scenario_id','generation_plant_id']],
        col_formats="(%s,%s)", table='generation_plant_scenario_member',
        database='switch_wecc', user=user, password=password, quiet=True)
    print "Successfully assigned pushed generation plants to a scenario!"

    # Recover original NOT NULL constraint
    query = 'ALTER TABLE "generation_plant" ALTER "load_zone_id" SET NOT NULL;'
    connect_to_db_and_run_query(query,
        database='switch_wecc', user=user, password=password, quiet=True)
    query = 'ALTER TABLE "generation_plant" ALTER "max_age" SET NOT NULL;'
    connect_to_db_and_run_query(query,
        database='switch_wecc', user=user, password=password, quiet=True)

    # Get the list of indexes of plants actually uploaded
    print "\nAssigning build years to generation plants..."
    query = 'SELECT * FROM generation_plant\
        JOIN generation_plant_scenario_member USING (generation_plant_id)\
        WHERE generation_plant_scenario_id = {}'.format(gen_scenario_id)
    gens_in_db = connect_to_db_and_run_query(query,
            database='switch_wecc', user=user, password=password, quiet=True)
    gen_indexes_in_db = gens_in_db[['generation_plant_id','eia_plant_code','energy_source','gen_tech']]

    # Create the df and upload it
    build_years_df = pd.merge(generators, gen_indexes_in_db,
        on=['eia_plant_code','energy_source','gen_tech'])[['generation_plant_id',
        'build_year','capacity']]
    build_years_df['generation_plant_existing_and_planned_scenario_id'] = gen_scenario_id
    build_years_df = build_years_df[[
        'generation_plant_existing_and_planned_scenario_id','generation_plant_id',
        'build_year','capacity']]
    connect_to_db_and_push_df(df=build_years_df,
        col_formats="(%s,%s,%s,%s)", table='generation_plant_existing_and_planned',
        database='switch_wecc', user=user, password=password, quiet=True)
    print "Successfully uploaded build years!"

    print "\nAssigning fixed and investment costs to generation plants..."
    cost_df = build_years_df.rename(columns={
        'generation_plant_existing_and_planned_scenario_id':
        'generation_plant_cost_scenario_id'}).drop('capacity', axis=1)
    cost_df['fixed_o_m'] = 0
    cost_df['overnight_cost'] = 0

    connect_to_db_and_push_df(df=cost_df,
        col_formats="(%s,%s,%s,%s,%s)", table='generation_plant_cost',
        database='switch_wecc', user=user, password=password, quiet=True)
    print "Successfully uploaded fixed and capital costs!"

    # Read hydro capacity factor data, merge with generators in the database, and upload
    print "\nUploading hydro capacity factors..."
    hydro_cf = read_output_csv('historic_hydro_capacity_factors_NARROW.tab').rename(
        columns={'Plant Code':'eia_plant_code','Prime Mover':'gen_tech'})
    hydro_cf = pd.merge(hydro_cf,gen_indexes_in_db[['generation_plant_id','eia_plant_code','gen_tech']],
        on=['eia_plant_code','gen_tech'], how='inner')
    hydro_cf.rename(columns={'Month':'month','Year':'year'}, inplace=True)
    hydro_cf.loc[:,'hydro_avg_flow_mw'] = hydro_cf.loc[:,'Capacity Factor'] * hydro_cf.loc[:,'Nameplate Capacity (MW)']
    hydro_cf.loc[:,'hydro_min_flow_mw'] = hydro_cf.loc[:,'hydro_avg_flow_mw'] / 2
    hydro_cf.loc[:,'hydro_simple_scenario_id'] = gen_scenario_id
    hydro_cf = hydro_cf[['hydro_simple_scenario_id','generation_plant_id',
        'year','month','hydro_min_flow_mw','hydro_avg_flow_mw']]

    connect_to_db_and_push_df(df=hydro_cf,
        col_formats="(%s,%s,%s,%s,%s,%s)", table='hydro_historical_monthly_capacity_factors',
        database='switch_wecc', user=user, password=password, quiet=True)
    print "Successfully uploaded hydro capacity factors!"



    print "\n-----------------------------"
    print "Aggregating projects by load zone..."

    # First, group by load zone, gen tech, energy source and heat rate
    # (while calculating a capacity-weighted average heat rate)
    gens_in_db['hr_group'] = gens_in_db['full_load_heat_rate'].fillna(0).round()
    gens_in_db['full_load_heat_rate'] *= gens_in_db['capacity_limit_mw']
    gens_in_db_cols = gens_in_db.columns
    gb = gens_in_db.groupby(['gen_tech','load_zone_id','energy_source',
        'hr_group'])
    aggregated_gens = gb.agg(
                {col:(sum if col in ['capacity_limit_mw','full_load_heat_rate']
                    else 'max') for col in gens_in_db.columns}).reset_index(drop=True)
    aggregated_gens['full_load_heat_rate'] /= aggregated_gens['capacity_limit_mw']
    aggregated_gens = aggregated_gens[gens_in_db_cols]

    # Now, clean up columns
    aggregated_gens['name'] = ('LZ_' + aggregated_gens['load_zone_id'].map(str) + '_' +
        aggregated_gens['gen_tech'] + '_' + aggregated_gens['energy_source'] + '_HR_' +
        aggregated_gens['hr_group'].map(int).map(str))
    aggregated_gens.drop(['generation_plant_id','generation_plant_scenario_id',
        'eia_plant_code','latitude','longitude','county','state'],
        axis=1, inplace=True)
    print "Aggregated into {} projects.".format(len(aggregated_gens))

    # First, delete previously stored projects for the aggregated plants
    gen_scenario_id = 3.0

    query = 'DELETE FROM generation_plant_scenario_member\
        WHERE generation_plant_scenario_id = {}'.format(gen_scenario_id)
    connect_to_db_and_run_query(query,
            database='switch_wecc', user=user, password=password, quiet=True)

    query = 'DELETE FROM generation_plant_existing_and_planned\
        WHERE generation_plant_existing_and_planned_scenario_id = {}'.format(gen_scenario_id)
    connect_to_db_and_run_query(query,
            database='switch_wecc', user=user, password=password, quiet=True)

    query = 'DELETE FROM generation_plant_cost\
        WHERE generation_plant_cost_scenario_id = {}'.format(gen_scenario_id)
    connect_to_db_and_run_query(query,
            database='switch_wecc', user=user, password=password, quiet=True)

    query = 'DELETE FROM hydro_historical_monthly_capacity_factors\
        WHERE hydro_simple_scenario_id = {}'.format(gen_scenario_id)
    connect_to_db_and_run_query(query,
            database='switch_wecc', user=user, password=password, quiet=True)

    # It is necessary to temporarily disable triggers when deleting from
    # generation_plant table, because of multiple fkey constraints
    query = 'SET session_replication_role = replica;\
            DELETE FROM generation_plant\
            WHERE generation_plant_id NOT IN\
            (SELECT generation_plant_id FROM generation_plant_scenario_member);\
            SET session_replication_role = DEFAULT;'
    connect_to_db_and_run_query(query,
            database='switch_wecc', user=user, password=password, quiet=True)
    print "\nDeleted previously stored projects for the load zone-aggregated EIA dataset (id 3). Pushing data..."

    query = 'SELECT last_value FROM generation_plant_id_seq'
    first_gen_id = connect_to_db_and_run_query(query,
        database='switch_wecc', user=user, password=password, quiet=True).iloc[0,0] + 1

    connect_to_db_and_push_df(df=aggregated_gens.drop(['hr_group','geom'], axis=1),
        col_formats=("(DEFAULT,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
            "%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL,NULL,NULL,NULL,NULL)"),
        table='generation_plant',
        database='switch_wecc', user=user, password=password, quiet=True)
    print "Successfully pushed aggregated project data!"

    query = 'SELECT last_value FROM generation_plant_id_seq'
    last_gen_id = connect_to_db_and_run_query(query,
        database='switch_wecc', user=user, password=password, quiet=True).iloc[0,0]

    print "\nAssigning all aggregated plants to scenario id {}...".format(gen_scenario_id)
    query = 'INSERT INTO generation_plant_scenario_member\
    (SELECT {}, generation_plant_id FROM generation_plant\
        WHERE generation_plant_id BETWEEN {} AND {})'.format(
            gen_scenario_id,first_gen_id, last_gen_id)
    connect_to_db_and_run_query(query,
        database='switch_wecc', user=user, password=password, quiet=True)
    print "Successfully assigned pushed generation plants to a scenario!"

    query = 'SELECT last_value FROM generation_plant_id_seq'
    last_gen_id = connect_to_db_and_run_query(query,
        database='switch_wecc', user=user, password=password, quiet=True)

    print "\nAssigning build years to generation plants..."
    query = 'SELECT * FROM generation_plant\
        JOIN generation_plant_scenario_member USING (generation_plant_id)\
        WHERE generation_plant_scenario_id = {}'.format(gen_scenario_id)
    aggregated_gens_in_db = connect_to_db_and_run_query(query,
            database='switch_wecc', user=user, password=password, quiet=True)

    aggregated_gens_in_db['hr_group'] = aggregated_gens_in_db['full_load_heat_rate'].fillna(0).round()
    aggregated_gens_in_db['generation_plant_existing_and_planned_scenario_id'] = gen_scenario_id
    gens_in_db = pd.merge(gens_in_db, generators[['eia_plant_code','energy_source',
        'gen_tech','capacity','build_year']],
        on=['eia_plant_code','energy_source','gen_tech'], suffixes=('','_y'))
    aggregated_gens_bld_yrs = pd.merge(aggregated_gens_in_db, gens_in_db,
        on=['load_zone_id','energy_source','gen_tech','hr_group'], suffixes=('','_y'))[[
        'generation_plant_existing_and_planned_scenario_id',
        'generation_plant_id','build_year','capacity']]
    aggregated_gens_bld_yrs_cols = list(aggregated_gens_bld_yrs.columns)

    gb = aggregated_gens_bld_yrs.groupby(aggregated_gens_bld_yrs_cols[:-1])
    aggregated_gens_bld_yrs = gb.agg(
        {col:(sum if col=='capacity' else 'max')
        for col in aggregated_gens_bld_yrs.columns}).reset_index(drop=True)
    aggregated_gens_bld_yrs = aggregated_gens_bld_yrs[aggregated_gens_bld_yrs_cols]

    connect_to_db_and_push_df(df=aggregated_gens_bld_yrs,
        col_formats="(%s,%s,%s,%s)",
        table='generation_plant_existing_and_planned',
        database='switch_wecc', user=user, password=password, quiet=True)
    print "Successfully pushed aggregated project build years data!"

    print "\nAssigning fixed and investment costs to generation plants..."
    aggregated_gens_costs = aggregated_gens_bld_yrs.rename(columns={
        'generation_plant_existing_and_planned_scenario_id':
        'generation_plant_cost_scenario_id'}).drop('capacity', axis=1)
    aggregated_gens_costs['fixed_o_m'] = 0
    aggregated_gens_costs['overnight_cost'] = 0

    connect_to_db_and_push_df(df=aggregated_gens_costs,
        col_formats="(%s,%s,%s,%s,%s)", table='generation_plant_cost',
        database='switch_wecc', user=user, password=password, quiet=True)
    print "Successfully uploaded fixed and capital costs!"

    print "\nUploading hydro capacity factors..."
    agg_hydro_cf = read_output_csv('historic_hydro_capacity_factors_NARROW.tab').rename(
        columns={'Plant Code':'eia_plant_code','Prime Mover':'gen_tech',
        'Month':'month','Year':'year'})
    agg_hydro_cf.loc[:,'hydro_avg_flow_mw'] = (agg_hydro_cf.loc[:,'Capacity Factor'] *
        agg_hydro_cf.loc[:,'Nameplate Capacity (MW)'])
    agg_hydro_cf.loc[:,'hydro_min_flow_mw'] = agg_hydro_cf.loc[:,'hydro_avg_flow_mw'] / 2
    # The drop_duplicates command avoids double-counting plants with multiple build_years
    agg_hydro_cf = pd.merge(agg_hydro_cf, gens_in_db[[
        'eia_plant_code','gen_tech','load_zone_id','generation_plant_id']].drop_duplicates(),
        on=['eia_plant_code', 'gen_tech'], how='inner')
    agg_hydro_cf['hydro_simple_scenario_id'] = gen_scenario_id
    gb = agg_hydro_cf.groupby(['load_zone_id','gen_tech','month','year'])
    agg_hydro_cf = gb.agg(
        {col:(sum if col in ['hydro_min_flow_mw','hydro_avg_flow_mw'] else 'max')
        for col in agg_hydro_cf.columns}).reset_index(drop=True)

    agg_hydro_cf = pd.merge(aggregated_gens_in_db, agg_hydro_cf,
        on=['load_zone_id', 'gen_tech'], how='inner', suffixes=('','_y'))
    agg_hydro_cf = agg_hydro_cf[['hydro_simple_scenario_id','generation_plant_id','year','month',
        'hydro_min_flow_mw','hydro_avg_flow_mw']]

    connect_to_db_and_push_df(df=agg_hydro_cf,
        col_formats="(%s,%s,%s,%s,%s,%s)", table='hydro_historical_monthly_capacity_factors',
        database='switch_wecc', user=user, password=password, quiet=True)
    print "Successfully uploaded hydro capacity factors!"


def assign_var_cap_factors():
    user = getpass.getpass('Enter username for the database:')
    password = getpass.getpass('Enter database password for user {}:'.format(user))
    print "\nWill assign variable capacity factors for WIND projects"
    print "(May take significant time)\n"
    # Assign average AMPL wind profile of each load zone to all projects in that zone
    for zone in range(1,51):
        print "Load zone {}...".format(zone)
        query = "INSERT INTO variable_capacity_factors\
                (SELECT generation_plant_id, timepoint_id, timestamp_utc, cap_factor, 1\
                FROM generation_plant\
                JOIN(\
                SELECT area_id, timepoint_id, timestamp_utc, avg(cap_factor) AS cap_factor, 1\
                FROM temp_ampl__proposed_projects_v3\
                JOIN temp_variable_capacity_factors_historical USING (project_id)\
                JOIN temp_load_scenario_historic_timepoints ON (hour=historic_hour)\
                JOIN raw_timepoint ON (timepoint_id = raw_timepoint_id)\
                WHERE area_id = {} AND technology_id = 4\
                GROUP BY 1,2,3\
                ORDER BY 1,2\
                ) AS factors ON (area_id = load_zone_id)\
                WHERE gen_tech = 'WT')".format(zone)
        connect_to_db_and_run_query(query,
                database='switch_wecc', user=user, password=password, quiet=True)
        print "Successfully assigned factors to projects in load zone {}.".format(zone)

    print "\nWill assign variable capacity factors for SOLAR PV projects"
    print "(May take significant time)\n"
    for zone in range(1,51):
        print "Load zone {}...".format(zone)
        query = "INSERT INTO variable_capacity_factors\
                (SELECT generation_plant_id, timepoint_id, timestamp_utc, cap_factor, 1\
                FROM generation_plant\
                JOIN(\
                SELECT area_id, timepoint_id, timestamp_utc, avg(cap_factor) AS cap_factor, 1\
                FROM temp_ampl__proposed_projects_v3\
                JOIN temp_variable_capacity_factors_historical USING (project_id)\
                JOIN temp_load_scenario_historic_timepoints ON (hour=historic_hour)\
                JOIN raw_timepoint ON (timepoint_id = raw_timepoint_id)\
                WHERE area_id = {} AND technology_id IN (6,25,26)\
                GROUP BY 1,2,3\
                ORDER BY 1,2\
                ) AS factors ON (area_id = load_zone_id)\
                WHERE gen_tech = 'PV')".format(zone)
        connect_to_db_and_run_query(query,
                database='switch_wecc', user=user, password=password, quiet=True)
        print "Successfully assigned factors to projects in load zone {}.".format(zone)

    print "\nSetting all capacity factors for January 1st 00:00-8:00 hrs to 0.0"
    for zone in range(1,51):
        query = "delete from variable_capacity_factors cf\
        using generation_plant gp\
        where gp.generation_plant_id = cf.generation_plant_id and\
        gen_tech = 'PV' and load_zone_id={} and\
        extract(day from timestamp_utc) = 1\
        and extract(month from timestamp_utc) = 1\
        and extract(hour from timestamp_utc) between 0 and 8".format(zone)
        connect_to_db_and_run_query(query,
            database='switch_wecc', user=user, password=password, quiet=True)
        print "Deleted existing cap factors for zone {} in that interval.".format(zone)

        query = "INSERT into variable_capacity_factors\
        (select generation_plant_id, timepoint_id, timestamp_utc, 0.0, 1\
        from temp_load_scenario_historic_timepoints\
        join raw_timepoint on (raw_timepoint_id=timepoint_id)\
        cross join generation_plant\
        where gen_tech = 'PV'\
        and load_zone_id = {}\
        and extract(day from timestamp_utc) = 1\
        and extract(month from timestamp_utc) = 1\
        and extract(hour from timestamp_utc) between 0 and 8)".format(zone)
        connect_to_db_and_run_query(query,
            database='switch_wecc', user=user, password=password, quiet=True)
        print "Inserted values of 0.0."


if __name__ == "__main__":
    finish_project_processing(2015)



def assign_states_to_counties():
    state_dict = {
        'AL': 'Alabama',
        'AK': 'Alaska',
        'AZ': 'Arizona',
        'AR': 'Arkansas',
        'CA': 'California',
        'CO': 'Colorado',
        'CT': 'Connecticut',
        'DE': 'Delaware',
        'FL': 'Florida',
        'GA': 'Georgia',
        'HI': 'Hawaii',
        'ID': 'Idaho',
        'IL': 'Illinois',
        'IN': 'Indiana',
        'IA': 'Iowa',
        'KS': 'Kansas',
        'KY': 'Kentucky',
        'LA': 'Louisiana',
        'ME': 'Maine',
        'MD': 'Maryland',
        'MA': 'Massachusetts',
        'MI': 'Michigan',
        'MN': 'Minnesota',
        'MS': 'Mississippi',
        'MO': 'Missouri',
        'MT': 'Montana',
        'NE': 'Nebraska',
        'NV': 'Nevada',
        'NH': 'New Hampshire',
        'NJ': 'New Jersey',
        'NM': 'New Mexico',
        'NY': 'New York',
        'NC': 'North Carolina',
        'ND': 'North Dakota',
        'OH': 'Ohio',
        'OK': 'Oklahoma',
        'OR': 'Oregon',
        'PA': 'Pennsylvania',
        'RI': 'Rhode Island',
        'SC': 'South Carolina',
        'SD': 'South Dakota',
        'TN': 'Tennessee',
        'TX': 'Texas',
        'UT': 'Utah',
        'VT': 'Vermont',
        'VA': 'Virginia',
        'WA': 'Washington',
        'WV': 'West Virginia',
        'WI': 'Wisconsin',
        'WY': 'Wyoming'
    }

    query = 'UPDATE us_counties uc SET state_name = cs.state\
        FROM (SELECT DISTINCT c.name, state, statefp, state_fips, c.gid\
        FROM us_counties c join us_states s ON c.statefp=s.state_fips) cs\
        WHERE cs.gid = uc.gid'
    connect_to_db_and_run_query(query, database='switch_wecc', user=user, password=password)


    for state_abr, state_name in state_dict.iteritems():
        query = "UPDATE us_counties SET state_name = '{}' WHERE state_name = '{}'".format(
            state_abr, state_name)
        connect_to_db_and_run_query(query, database='switch_wecc', user=user, password=password)
