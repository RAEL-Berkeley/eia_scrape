# Copyright 2017. All rights reserved. See AUTHORS.txt
# Licensed under the Apache License, Version 2.0 which is in LICENSE.txt
"""
Scrape data on existing and planned generators in the United States from the 
Energy Information Agency's data portal. Start with form EIA-860 which has
plant- and unit-level technology, location and various characteristics.

Done:
Download files, log and unzip

To Do: 
Complete investigation of files (1/2 done)
Parse files, aggregate and export
Determine if code for scraping the next datasets needs to live here or if it
can live in other files.
QA/QC on output

"""

import csv
import os
import pandas as pd

# Update the reference to the utils module after this becomes a package
from utils import download_file, download_metadata_fields, unzip

output_directory = "downloads"
log_path = os.path.join(output_directory, 'download_log.csv')
REUSE_PRIOR_DOWNLOADS = True


def scrape_eia860():
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)
    log_dat = []
    start_year, end_year = 2001, 2015
    file_list = ['eia860{}.zip'.format(year) for year in range(start_year, end_year+1)]
    for filename in file_list:
        local_path = os.path.join(output_directory, filename)
        if REUSE_PRIOR_DOWNLOADS and os.path.isfile(local_path):
            print "Skipping " + filename + " because it was already downloaded."
            continue
        print "Downloading " + local_path
        url = 'http://www.eia.gov/electricity/data/eia860/xls/' + filename
        meta_data = download_file(url, local_path)
        log_dat.append(meta_data)

    # Only write the log file header if we are starting a new log
    write_log_header = not os.path.isfile(log_path)
    with open(log_path, 'ab') as logfile:
        logwriter = csv.writer(logfile, delimiter='\t',
                               quotechar="'", quoting=csv.QUOTE_MINIMAL)
        if write_log_header:
            logwriter.writerow(download_metadata_fields)
        logwriter.writerows(log_dat)
    
    return file_list


def main():
    file_list = scrape_eia860()
    # Only unzip the last year of generator listings for now.
    # Note, the file listings/data structures are different prior to 2013.
    unzip([file_list[-1]])


def parse_dat():
    path = 'eia8602015/2___Plant_Y2015.xlsx'
    plants = pd.read_excel(path, sheetname=0, skiprows=1)
    plants.set_index('Plant Code')

    path = 'eia8602015/3_1_Generator_Y2015.xlsx'
    generators_raw = pd.read_excel(path, sheetname=None, skiprows=1)
    for sheet in generators_raw.keys():
        generators_raw[sheet]['Operational Status'] = sheet
    generators = generators_raw[u'Operable']
    generators.append(generators_raw[u'Proposed'])
    generators = pd.merge(generators, plants, 
        on=['Utility ID', 'Utility Name', 'Plant Code', 'Plant Name', 'State', 'County', 'Sector', 'Sector Name'],
        suffixes=('', ''))

    # Group by Plant, Technology, Unit Code
    # 'Plant Code', 'Technology', 'Unit Code'
    # Plant-level data
    # 'Utility ID', 'Utility Name', 'Plant Name', 'Street Address', 'City', 'State', 'Zip', 'County', 'Latitude', 'Longitude', 'NERC Region', 'Balancing Authority Code', 'Balancing Authority Name'
    # Group data (sum)
    # 'Nameplate Capacity (MW)', 'Summer Capacity (MW)', 'Winter Capacity (MW)', 'Minimum Load (MW)',
    # Plant-level data or Unit-level data?
    # 'Status', 'Operating Year', 'Planned Retirement Year'
    # 'Associated with Combined Heat and Power System', 'Topping or Bottoming'
    # 'Energy Source 1'
    # Ignore multi-fuel for now: 'Cofire Fuels?', 'Energy Source 2', 'Energy Source 3', 'Energy Source 4', 'Energy Source 5', 'Energy Source 6'
    # 'Carbon Capture Technology?'
    # 'Time from Cold Shutdown to Full Load' 
    # 10M -> Quickstart
    # 1H, 12H (other reserves)
    # OVER (operated as baseload/flexible baseload; presumably day+ start times)
    # '' -> Mostly wind & solar. Handful of other generators
    # Combined cycle considerations
    # 'Duct Burners' means the overall unit can get heat separately from the exhaust gas
    # 'Can Bypass Heat Recovery Steam Generator?' - means the combustion turbine operate independently of the steam generator. In 2015, 247 gas CT units were capable of this.
    
    # Wind only; Can ignore for now. 3_2_Wind_Y2015.xlsx 'Number of Turbines',
    # 'Predominant Turbine Manufacturer', 'Predominant Turbine Model Number',
    # 'Design Wind Speed (mph)', 'Wind Quality Class', 'Turbine Hub Height (Feet)'
    # Solar has similar data available

    # Generator costs from schedule 5 are hidden for individual generators,
    # but published in aggregated form. 2015 data is expected to be available
    # in Feb 2017. Data only goes back to 2013; I don't know how to get good
    # estimates of costs of older generators.
    # http://www.eia.gov/electricity/generatorcosts/
    
    # Heat rates: My working plan is to pull plant output and fuel inputs on a
    # monthly basis, calculate average monthly heat rates, inspect the data
    # for a handful of plants and compare the results against generic heat
    # rates for the given generator types. If things look reasonable, use that
    # data series to estimate effective heat rates. Switch would like full
    # load heat rates which may correspond to monthly heat rates where the
    # plant had high cap factors. We could also use average heat rates based
    # on historical cap factors, or we could try to estimate a heat rate curve
    # (aka input-output curve) based on the monthly timeseries. Well, that last
    # approach should probably wait until the second pass.
    # If there are other data sources that I missed that would allow a more
    # direct determination of heat rates, use those instead.
    # Heat rate functionality could live in a separate file.


if __name__ == "__main__":
    main()