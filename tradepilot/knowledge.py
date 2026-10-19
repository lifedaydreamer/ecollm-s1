"""Versioned keyword/dense retrieval with optional local BGE models. No implicit downloads."""
import hashlib
import json
import math
import os
import re
from pathlib import Path


class KnowledgeStore:
    def __init__(self,path):
        self.rows=json.loads(Path(path).read_text())
        if any(not r.get("license") or not r.get("source") or not r.get("version") for r in self.rows):
            raise ValueError("知识条目必须包含来源、许可和版本")
        self.snapshot=hashlib.sha256(Path(path).read_bytes()).hexdigest()
        self.embedder=self.reranker=None
        self.vectors=None
        if os.getenv("TRADEPILOT_EMBEDDING_PATH"):
            from sentence_transformers import SentenceTransformer, CrossEncoder
            self.embedder=SentenceTransformer(os.environ["TRADEPILOT_EMBEDDING_PATH"],device="cpu",local_files_only=True)
            self.vectors=self.embedder.encode([r["text"] for r in self.rows],normalize_embeddings=True)
            if os.getenv("TRADEPILOT_RERANKER_PATH"):
                self.reranker=CrossEncoder(os.environ["TRADEPILOT_RERANKER_PATH"],device="cpu",local_files_only=True)

    def search(self,query,topics=None):
        terms=set(re.findall(r"[a-zA-Z]+|[\u4e00-\u9fff]",query.lower()))
        scored=[]
        for i,row in enumerate(self.rows):
            if topics is not None and not set(topics).intersection(row.get("topics", [])):
                continue
            words=set(re.findall(r"[a-zA-Z]+|[\u4e00-\u9fff]",row["text"].lower()))
            score=len(terms&words)/math.sqrt(max(len(words),1))
            if score: scored.append((i,score))
        ranks=[sorted(scored,key=lambda x:x[1],reverse=True)[:20]]
        if self.embedder:
            v=self.embedder.encode([query],normalize_embeddings=True)[0]
            dense = [(i,score) for i,score in enumerate(self.vectors@v)
                     if topics is None or set(topics).intersection(self.rows[i].get("topics", []))]
            ranks.append(sorted(dense,key=lambda x:x[1],reverse=True)[:20])
        fused={}
        for ranking in ranks:
            for rank,(index,_) in enumerate(ranking):
                fused[index]=fused.get(index,0)+1/(60+rank+1)
        indices=sorted(fused,key=fused.get,reverse=True)[:30]
        if self.reranker and indices:
            scores=self.reranker.predict([(query,self.rows[i]["text"]) for i in indices])
            indices=[i for i,_ in sorted(zip(indices,scores),key=lambda x:x[1],reverse=True)]
        return [{**self.rows[i],"snapshot":self.snapshot,"usage":"retrieved_reference_not_applicability_decision"} for i in indices[:3]]


def finding_topics(finding):
    """Deterministic routing avoids attaching unrelated official references."""
    text = finding["key"] + " " + finding["title"]
    labels = {"seller":"卖方", "buyer":"买方", "total":"总额", "currency":"币种", "quantity":"数量",
              "deposit_percent":"预付款", "payment_days":"账期", "payment_trigger":"触发", "incoterm":"贸易术语",
              "shipment_date":"装运", "delivery_date":"交付", "inspection":"验收", "liability":"责任", "dispute":"争议",
              "unit_price":"单价", "item":"商品", "arithmetic":"行金额"}
    return [key for key,label in labels.items() if key in text or label in text]
