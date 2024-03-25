import os
import pandas as pd
import argparse

def read_files_to_parquet(folder_path, extension, output_file):
    data = []
    for root, _, files in os.walk(folder_path):
        for filename in files:
            if filename.endswith(extension):
                file_path = os.path.join(root, filename)
                with open(file_path, 'r', encoding='utf-8') as file:
                    content = file.read()
                    data.append(content)

    df = pd.DataFrame({'content': data})
    df.to_parquet(output_file)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert files to Parquet format")
    parser.add_argument("--folder_path", help="Path to the folder containing files", default="/pfs/data")
    parser.add_argument("--extension", help="File extension to filter (e.g., .py)")
    parser.add_argument("--output_file", help="Output Parquet file path", default="/pfs/out/data.parquet")
    args = parser.parse_args()

    read_files_to_parquet(args.folder_path, args.extension, args.output_file)
