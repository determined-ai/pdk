# This script is used to create three files: train.csv, validation.csv, test.csv

'''
For the sentiment analysis, we used Financial PhraseBank from Malo et al. (2014). The dataset can be downloaded from this link. If you want to train the model on the same dataset, after downloading it, you should create three files under the data/sentiment_data folder as train.csv, validation.csv, test.csv. To create these files, do the following steps:
Link: https://www.researchgate.net/publication/251231364_FinancialPhraseBank-v10
1. Download the Financial PhraseBank from the above link.
2. Get the path of Sentences_50Agree.txt file in the FinancialPhraseBank-v1.0 zip.
3. Run the datasets script: python scripts/datasets.py --data_path <path to Sentences_50Agree.txt>
'''

import argparse
import os

import pandas as pd
from sklearn.model_selection import train_test_split


def load_files(input_dir):
    df_combined = pd.DataFrame()
    for dirpath, dirs, files in os.walk(input_dir):
        for file in files:
            if file.startswith('Sentences_'):
                print(f'Reading in {file}')
                df = pd.read_csv(os.path.join(dirpath, file), sep='.@', names=['text','label'], encoding="ISO-8859-1", engine='python')
                df_combined = pd.concat([df_combined, df], axis=0)
    return df_combined


def main(input_dir, output_dir):
    data = load_files(input_dir)

    train, test = train_test_split(data, test_size=0.2, random_state=0)
    train, valid = train_test_split(train, test_size=0.1, random_state=0)

    train.to_csv(os.path.join(output_dir, 'train.csv'), sep='\t')
    test.to_csv(os.path.join(output_dir, 'test.csv'), sep='\t')
    valid.to_csv(os.path.join(output_dir, 'validation.csv'), sep='\t')


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input_dir",
        default="data",
        help="Name of input directory that has the labeled Phrasebank Data",
    )
    parser.add_argument(
        "--output_dir",
        default="output",
        help="Name of output directory that stores the combined data",
    )
    args = parser.parse_args()
    main(
        input_dir=args.input_dir,
        output_dir=args.output_dir
    )
