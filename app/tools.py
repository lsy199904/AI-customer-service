"""Explicit business-tool boundary. Tools are disabled until real adapters are registered.

Handlers receive server-authenticated identity separately from model supplied arguments.
Write tools are deliberately not executable without an external approval/idempotency adapter.
"""
from dataclasses import dataclass
from typing import Callable
from pydantic import BaseModel,ConfigDict,Field
from langchain_core.tools import StructuredTool

class QueryArguments(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    question:str=Field(min_length=1,max_length=2000)

@dataclass(frozen=True)
class ToolContext:
    tenant_id:str
    user_id:str
    session_id:str
    request_id:str

@dataclass
class BusinessTool:
    name:str
    description:str
    handler:Callable
    authorize:Callable
    mutating:bool=False

class ToolRegistry:
    def __init__(self):self.tools={}
    def register(self,tool):
        if tool.name in self.tools:raise ValueError('重复工具名')
        if tool.mutating:raise ValueError('写入工具须先接入人工确认和幂等适配器，当前禁止注册')
        self.tools[tool.name]=tool
    def available(self):return bool(self.tools)
    def invoke(self,name,args,context):
        tool=self.tools.get(name)
        if tool is None:raise LookupError('业务接口尚未接入')
        if not tool.authorize(context):raise PermissionError('当前用户无权使用此业务工具')
        def call(question):return tool.handler(context,question=question)
        wrapped=StructuredTool.from_function(call,name=tool.name,description=tool.description,args_schema=QueryArguments)
        result=wrapped.invoke(args)
        if not isinstance(result,dict) or set(result)-{'answer','reference'} or not isinstance(result.get('answer'),str):
            raise ValueError('业务工具返回结构无效')
        if len(result['answer'])>12000:raise ValueError('业务返回过长')
        return result
