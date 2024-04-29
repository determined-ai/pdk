import os
import argparse
import chromadb
import pandas as pd
from pathlib import Path
from chromadb.utils import embedding_functions
from langchain.text_splitter import RecursiveCharacterTextSplitter
from typing import Any, Dict, List, Mapping, Union, cast
from chromadb.api.types import (
    Document,
    Documents,
    Embedding,
    Image,
    Images,
    EmbeddingFunction,
    Embeddings,
    is_image,
    is_document,
)

def main(csv_path,path_to_db):
    settings = chromadb.get_settings()
    settings.allow_reset = True

    print(f"--> Creating/resetting db at {path_to_db}...")

    db = chromadb.PersistentClient(path=path_to_db, settings=settings)

    print("--> Done Creating DB!")
    db.reset()

    model_path=args.emb_model_path

    print("--> Loading {}...".format(model_path))

    emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=model_path, device="cpu"
    )

    print("--> Done Loading DB!")

    collection = db.create_collection(name="HPE_press_releases", embedding_function=emb_fn)

    data_path = csv_path
    df = pd.read_csv(data_path)
    LEN=df.shape[0]
    collection.add(
        documents=[df.iloc[i]['Content'] for i in range(LEN)],
        metadatas=[{'Title':df.iloc[i]['Title'],'Content':df.iloc[i]['Content'],'Date':df.iloc[i]['Date']} for i in range(LEN)],
        ids=[f'id{str(i)}' for i in range(LEN)]
    )

    query = "How were HPE's earnings in 2022?"
    results = collection.query(query_texts=[query], n_results=5)
    print("query: ",query, "results: ",results['documents'])

if __name__ == '__main__':
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--path_to_db',type=str, default='/run/determined/workdir/shared_fs/rag_db/', help='DB location')
    parser.add_argument('--emb_model_path',type=str, default='/run/determined/workdir/shared_fs/model/minilm', help='path to locally saved sentence transformer model')

    parser.add_argument('--csv_path',type=str, default='/pfs/process_xml/hpe_press_releases.csv', help='path to csv containing press releases')
    args = parser.parse_args()

    # Create Vector DB folder if it doesn't exist
    Path(args.path_to_db).mkdir(parents=True, exist_ok=True)

    main(args.csv_path,args.path_to_db)
