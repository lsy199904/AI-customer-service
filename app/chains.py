"""LangChain components over existing versioned storage and model transports."""
from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda
from langsmith import tracing_context
from pydantic import PrivateAttr


class KnowledgeRetriever(BaseRetriever):
    """One retriever per invocation keeps reports isolated between concurrent requests."""
    knowledge: Any
    _report: dict=PrivateAttr(default_factory=dict)

    @property
    def report(self):return self._report

    def _get_relevant_documents(self,query,*,run_manager):
        self._report=self.knowledge.assess(query)
        return [Document(page_content=record['content'],metadata={
            'record':record,'score':score,'source_id':record['id'],
            'source_file':record.get('source_file',''),'source_pages':record.get('source_pages',[])
        }) for score,record,_ in self._report.get('hits',[])]


def retrieve(knowledge,query):
    retriever=KnowledgeRetriever(knowledge=knowledge)
    chain=retriever | RunnableLambda(lambda documents:{
        'retrieval':retriever.report,
        'evidence':[document.metadata['record'] for document in documents],
    },name='traceable_evidence')
    # Customer content is never automatically sent to a tracing SaaS.
    with tracing_context(enabled=False):return chain.invoke(query)
