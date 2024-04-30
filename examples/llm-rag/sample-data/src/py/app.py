import os
import chromadb
import requests
import chainlit as cl
from datetime import datetime

api_host = os.environ.get("API_HOST")
api_port = os.environ.get("API_PORT")
RAG_DB_PATH=os.environ.get("DB_PATH")

print(f"API Host: {api_host} | API Port: {api_port} | DB RAG PATH: {RAG_DB_PATH}")

path = RAG_DB_PATH
settings = chromadb.get_settings()
settings.allow_reset = True
db = chromadb.PersistentClient(path=path,settings=settings)
collection = db.get_collection("HPE_press_releases")

titan_url = "http://{}:{}/generate_stream".format(api_host,api_port)

print("Titan URL: ",titan_url)

@cl.on_message  # this function will be called every time a user inputs a message in the UI
async def main(message: cl.Message):
    msg = cl.Message(
        content="",
    )

    results = collection.query(query_texts=[message.content], n_results=5)
    
    date_strings = [i['Date'] for i in results['metadatas'][0]]
    # Your list of datetime strings
    # date_strings = ['2017-11-21', '2018-03-19', '2022-01-28', '2023-06-20', '2022-04-27']
    # Step 1: Parse strings into datetime objects
    date_objects = [datetime.fromisoformat(date_str) for date_str in date_strings]

    # Step 2: Extract year, month, and day
    formatted_dates = [dt.strftime('%Y-%m-%d') for dt in date_objects]

    # Step 3: Sort datetime objects while keeping track of original indices
    sorted_dates_with_indices = sorted(enumerate(zip(date_objects, formatted_dates)),
                                       key=lambda x: x[1][0], reverse=True)

    # Extract sorted dates and original indices
    sorted_dates = [date_str for _, (dt, date_str) in sorted_dates_with_indices]
    original_indices = [index for index, _ in sorted_dates_with_indices]

    # Print the result
    print("Sorted Dates:", sorted_dates)
    print("Original Indices:", original_indices)
    results = [results["documents"][0][original_indices[0]]]# get the first document
    await show_sources(results)

    results2 = "\n\n".join(results)
    results2 = results2[:8500]
    print("len(results2): ",len(results2))
    print("results2: ",results2)
    prompt = f"[INST]`{results2}`. Using the above information, answer the following question: {message.content}. Answer concisely at most in three sentences. Respond in a natural way, like you are having a conversation with a friend.[/INST]"
    print("=========prompt=============: ")
    print(prompt)
    print("=========end_of_prompt=============")
    params={ 'generate_max_length': 300,
        'no_repeat_ngram_size': 0,
        'sampling_topk': 50,
        'sampling_topp': 0.95,
        'sampling_temperature': 0.3,
        'repetition_penalty': 1.0}
    
    json = {"text": prompt, **params}
    response = requests.post(titan_url, json=json, stream=True)
    response.encoding = "utf-8"
    
    print("response: ", response.content)
    
    for text in response.iter_content(chunk_size=1, decode_unicode=True):
        await msg.stream_token(text)

    await msg.send()


async def show_sources(results):
    await cl.Message(content="").send()