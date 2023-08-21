from transformers import (BertConfig, BertForSequenceClassification,
                          BertTokenizer)

MODEL_CLASSES = {
    "bert_for_classification": (BertConfig, 
    BertTokenizer, 
    BertForSequenceClassification),
}