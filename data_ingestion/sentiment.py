"""Transparent offline baseline; FinBERT is optional and must be explicitly selected."""
import re

class Sentiment:
    def __init__(self,finbert=False):
        self.pipeline=None
        if finbert:
            from transformers import pipeline
            self.pipeline=pipeline('text-classification',model='ProsusAI/finbert',top_k=None)
    def analyze(self,text):
        if self.pipeline:
            p={r['label']:r['score'] for r in self.pipeline(text[:2000])[0]}
            score=p.get('positive',0)-p.get('negative',0);method='FinBERT'
        else:
            words=set(re.findall(r'[a-z]+',text.lower()));pos=len(words&{'growth','raises','raise','beat','profit','strong','surge'});neg=len(words&{'loss','cuts','uncertainty','miss','falls','risk','weak'})
            score=(pos-neg)/max(pos+neg,1);method='lexicon baseline'
        topic='macro' if re.search(r'fed|inflation|rate|gdp',text,re.I) else 'earnings' if re.search(r'earnings|profit|revenue',text,re.I) else 'market'
        return dict(sentiment=score,category=topic,sentiment_method=method)
