"""数据访问层（Repository）。

职责：封装 SQLAlchemy 读写，接收调用方传入的 Session。
不创建/关闭 Session，也不 commit / rollback；事务由 Service 协调。
"""
