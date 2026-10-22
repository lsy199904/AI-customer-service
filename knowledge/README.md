# 旧版知识整理归档

正式语义问答维护 `../knowledge_sources/` 的Word/PDF等文档，详见 `../docs/知识文档管理.md`。本目录与旧JSONL保留供原型、兼容模式和历史引用使用，不作为默认语义库。

旧版有134条客户知识：产品体系7条、销售FAQ28条、Hub操作手册7条、AI Token术语92条。本目录4份Markdown是可读快照，旧JSONL在 `../data/knowledge.jsonl`。条目保留标题、正文、原文件名、版本与PDF物理页码。HTML术语没有物理页码。Markdown使用 `<<<KB_SPLIT>>>` 区分条目。

两份飞书快捷方式没有本地正文，未获取或转录。安全审计历史样例、AICC图文资料、Edge管理员手册、内部销售话术和待确认安全承诺没有进入客户检索数据。来源清单保留原材料名称及哈希，原PDF未打入代码包。

新Word支持认证下载对应修订的快照；旧JSONL仅能查看条目，原PDF仍需另外受控托管后配置SOURCE_BASE_URL。本目录Markdown和JSONL不参与新Word库的增量更新。若单独修改离线原型资料，需更新JSONL并运行build_prototype.py；这不会更新正式语义库。资料没有经过线上产品状态实时核验。
