import os
import re
import fitz
import argparse
import pandas as pd
from tqdm import tqdm
from bs4 import BeautifulSoup
from datetime import datetime

def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    text = ''

    for page_num in range(doc.page_count):
        page = doc[page_num]
        text += page.get_text()

    doc.close()
    return text

def extract_page_info_from_xml(xml_file):
    """
    Extract page information from an XML file.

    Args:
        xml_file (str): The path to the XML file to process.

    Returns:
        dict: A dictionary containing the page title and extracted text.
              The dictionary has the following structure:
              {
                  'page_title': str,
                  'extracted_text': List[str]
              }
    """
    with open(xml_file, "r", encoding="utf-8") as file:
        xml_content = file.read()

    soup = BeautifulSoup(xml_content, "xml")

    # Extract the pageTitle attribute
    page_title = soup.find("jcr:content").get("pageTitle")
    display_date = soup.find("jcr:content").get("displayDate")
    tag_pattern = re.compile(r"^textonlycomponent_")

    # Find all tags that match the pattern
    matching_tags = soup.find_all(tag_pattern)

    # Extract the text content from the matching tags
    extracted_text = []
    for tag in matching_tags:
        html_string = tag.get("textOnly", "")
        html_soup = BeautifulSoup(html_string, "html.parser")
        text = html_soup.get_text()
        extracted_text.append(text)

    return page_title, display_date, "\n".join(extracted_text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process a file.")
    parser.add_argument("--xml-directory", help="Path to the directory of XML file")
    parser.add_argument("--pdf-directory", help="Path to the directory of PDF file")
    parser.add_argument("--custom-csv-input", help="Path to a custom csv file with examples")
    parser.add_argument("--out-dir", help="path to final csv")
    args = parser.parse_args()

    xml_directory = args.xml_directory

    xml_files = []
    for root, dirs, files in os.walk(xml_directory):
        for file in files:
            if file.endswith(".xml"):
                xml_files.append(os.path.join(root, file))
    print("Number of examples: ", len(xml_files))

    page_titles = []
    display_dates = []
    extracted_texts = []
    for xml_f in tqdm(xml_files):
        page_title, display_date, extracted_text = extract_page_info_from_xml(xml_f)
        if page_title is not None:
            page_titles.append(page_title)
            if display_date is not None:
                date_object = datetime.strptime(display_date[6:], "%Y-%m-%dT%H:%M:%S.%f%z")
                display_dates.append(date_object.strftime('%Y-%m-%d'))
            else:
                display_dates.append(display_date)
            extracted_texts.append(extracted_text)

    print("Number of examples after filtering: ", len(page_titles), len(extracted_texts))

    pdf_directory = args.pdf_directory

    pdf_files = []
    for root, dirs, files in os.walk(pdf_directory):
        # Check if the current directory contains ".ipynb_checkpoints/"
        if ".ipynb_checkpoints" in root:
            continue

        for file in files:
            if file.endswith(".pdf"):
                pdf_files.append(os.path.join(root, file))

    print("Number of pdf examples: ", len(pdf_files))
    
    # Example usage
    if len(pdf_files)>0:
        for f in pdf_files:
            extracted_text = extract_text_from_pdf(f)
            # Print or use the extracted text as needed
            #print(extracted_text)
            extracted_texts.append(extracted_text)
            display_dates.append(datetime.now().date())
            page_titles.append(None)
    
    d = {
        "Title": page_titles,
        "Date": display_dates,
        "Content": extracted_texts,
        "URL": None,
    }
    
    print("Number of xml+pdf examples: ",len(extracted_texts))
    
    df = pd.DataFrame(d)
    
    print("Loading: {}...".format(args.custom_csv_input))
    
    df2 = pd.read_csv(args.custom_csv_input)
    
    print("number of press releases: ",df2.shape[0])
    
    # Define a function to parse the date string
    def parse_date(date_string):
        d = datetime.strptime(date_string, "%B %d, %Y")
        # print(d.strftime('%Y-%m-%d'))
        return d.strftime('%Y-%m-%d')

    # Apply the function to the 'Date' column
    df2['Date'] = df2['Date'].apply(parse_date)
    
    print("df2['Date']: ",df2['Date'])
    
    df3 = pd.concat([df,df2])
    
    print("Number of final examples: ",df3.shape[0])
    print("Saving parsed xml articles to a csv...")
    
    df3.to_csv(args.out_dir, index=None)
    
    print("Done!")