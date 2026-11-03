"""Bounded title equivalence, independent of rank fusion and score thresholds.

Only a complete operation + product identifier can omit one generic role noun.
No per-product aliases or fuzzy substring promotion are allowed here.
"""
import re

OPERATIONS=('安装','部署','配置','升级','卸载')
ROLE_NOUNS=('负载均衡器','负载均衡','数据库','服务器','组件','服务','缓存','集群')
STRENGTH={'normalized_title':3,'procedure_title':2,'operation_product_alias':2,'related_prefix':1}
_ACTION='(?:'+'|'.join(OPERATIONS)+')'
_OPERATION=re.compile('('+_ACTION+r')([a-z][a-z0-9]{2,})')
_REVERSE=re.compile(r'([a-z][a-z0-9]{2,})(?:如何|怎么)?('+_ACTION+')')
_ROLES='(?:'+'|'.join(ROLE_NOUNS)+')'


def classify(subject,procedure,target):
    kind='normalized_title' if len(subject)>=4 and subject==target else None
    operation=_OPERATION.fullmatch(procedure);reverse=_REVERSE.fullmatch(procedure)
    canonical=operation[1]+operation[2] if operation else reverse[2]+reverse[1] if reverse else None
    if kind is None and canonical and re.fullmatch(re.escape(canonical)+_ROLES,target):kind='operation_product_alias'
    if procedure!=subject and len(procedure)>=4 and kind is None:
        if procedure==target:kind='procedure_title'
        elif target.startswith(procedure):kind='related_prefix'
    return {'kind':kind,'strength':STRENGTH.get(kind,0),'strong':kind in ('normalized_title','procedure_title','operation_product_alias')}
