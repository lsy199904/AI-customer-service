"""LangChain components over existing versioned storage and model transports."""
import re
from typing import Any
import unicodedata

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda
from langsmith import tracing_context
from pydantic import PrivateAttr


class KnowledgeRetriever(BaseRetriever):
    """One retriever per invocation keeps reports isolated between concurrent requests."""
    knowledge: Any
    preferred_id: str | None=None
    _report: dict=PrivateAttr(default_factory=dict)

    @property
    def report(self):return self._report

    def _get_relevant_documents(self,query,*,run_manager):
        self._report=(self.knowledge.assess(query,preferred_id=self.preferred_id) if self.preferred_id and getattr(self.knowledge,'supports_selection',False) else self.knowledge.assess(query))
        return [Document(page_content=record['content'],metadata={
            'record':record,'score':score,'source_id':record['id'],
            'source_file':record.get('source_file',''),'source_pages':record.get('source_pages',[])
        }) for score,record,_ in self._report.get('hits',[])]


def glossary_definition(knowledge, query):
    """Match an explicit definition request to an exact heading in active glossary text."""
    text = unicodedata.normalize('NFKC', query).strip()
    request = re.fullmatch(
        r'(?:请问\s*)?([\w][\w .+/-]{0,39}?)\s*(?:是什么|是什么意思|指什么|是指什么|的含义(?:是什么)?)[\s?.!。！]*',
        text,
    )
    if request is None:
        request = re.fullmatch(r'(?:请问\s*)?什么是\s*([\w][\w .+/-]{0,39}?)[\s?.!。！]*', text)
    if request is None:
        return None
    term = ' '.join(request[1].casefold().split())
    matches = []
    for row in knowledge.rows.values():
        if not re.search(r'(?:名词|术语)(?:解释|释义|表)', row['title']):
            continue
        lines = [line.strip() for line in row['content'].splitlines() if line.strip()]
        for heading, definition in zip(lines, lines[1:]):
            label = re.fullmatch(r'([\w][\w .+/-]{0,39}?)(?:\s*\(([\w][\w .+/-]{0,39})\))?',
                                 unicodedata.normalize('NFKC', heading))
            if label is None or not re.search('[。，；,;]', definition):
                continue
            if term in {' '.join(alias.casefold().split()) for alias in label.groups() if alias}:
                matches.append({**row, 'content': f'{heading}\n{definition}'})
    return matches[0] if len(matches) == 1 else None


def retrieve(knowledge,query,preferred_id=None):
    if preferred_id is None and (definition := glossary_definition(knowledge, query)) is not None:
        return {'retrieval': {'matched': True, 'method': 'glossary_definition', 'query': query, 'hits': []},
                'evidence': [definition]}
    retriever=KnowledgeRetriever(knowledge=knowledge,preferred_id=preferred_id)
    chain=retriever | RunnableLambda(lambda documents:{
        'retrieval':retriever.report,
        'evidence':[document.metadata['record'] for document in documents],
    },name='traceable_evidence')
    # Customer content is never automatically sent to a tracing SaaS.
    with tracing_context(enabled=False):return chain.invoke(query)
