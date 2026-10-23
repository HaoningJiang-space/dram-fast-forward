# 干扰感知符号执行与依赖图实验

2026-10-23。结论：**应继续研究符号/多面体模型，但不能把毫秒级oracle图遍历称为在线模拟器加速。**
共享总线下已有精确可利用区间；当前完整收益约1.5×，主要未解问题是低成本依赖发现与维护。

## 1. 四个问题分别验证

| 子问题 | 实现和结果的性质 |
|---|---|
| A：全局隔离 | 保留首轮控制；0%仅刻画旧守卫 |
| B：允许其他bank工作 | 按物理资源作用域规划，保持真实接纳与反馈，在线执行 |
| C：已知顺序求值 | 参考提供顺序和必要策略决策，编译时序/队列依赖，属于oracle诊断 |
| D：不预知顺序 | 当前队列/行/时序的充分证书；破坏后物化并回退，在线执行 |

`bank_affine`要求地址固定步长；`bank_rowhit`使用地址不同但时序等价的READ投影；
`bank_hybrid`在后者回退中启用prerequisite增量缓存。不是完整多面体编译器。
证明条件见[方法论](RESEARCH_METHOD.md)。

## 2. 总线竞争没有省略

新增[8bank共享配置](../configs/shared-bus-8bank.yaml)：统一FR-FCFS队列、每拍一条命令、
共享RD/WR burst间隔与方向切换、跨bank ACT间隔与四次激活窗口、all-bank PREA/refresh。
普通逐拍和符号路径使用同一份物理实现。原独立TSV配置另作控制，不改变架构制造加速。

这是自定义3D模型上的验证fixture：400MHz、256B事务、8拍burst，nRRDS=4、nFAW=24、
nRFC=64、nREFI=3900；不是已校准或完整JEDEC认证的商业器件。

独立checker验证471,344条命令和214,176个数据命令：161,786次跨bank数据切换、448次
读写切换、129,619次四ACT窗口检查、448次refresh，均无声明约束违规或数据burst重叠。
[证据](../results/interference_20261023/evidence/shared_full_bus_check_v4.json)。

故意在离线图省略共享RD/WR总线边，会有448,812个命令和220,788个callback周期错误，
最大519拍。此负对照不参与在线加速表。

## 3. 流量范围与精确性

E是原native捕获的三次局部Up/Gate，M32/N1792/K8192、付费core Split-K4，224,896项，
含211,456次READ。完整回放的是该窗口，不是80层Dense或完整FFN。
共享配置把同一流作为外部到达输入并重新承担回压，不声称重新采集了共享硬件的加速器闭环。

两个配置各含9个合成/真实前缀/边界case、1个完整E、20个混合闭环随机种子、3个针对性case。
合计**66案例、198次计划/参考比较、284,039次资源退出状态比较通过**。比较逐字节原始命令、
接纳/拒绝、callback、资源退出状态及最终完整世界状态。共享bus的证书覆盖整个channel；
不是每次局部退出扫描全世界。闭环证据来自合成反馈，尚非完整加速器集成。

v1曾在观察时重复物化已取消计划，将cycle1034的READ history写回旧1026。该版本被拒绝；
修复后重跑矩阵。[失败记录](../results/interference_20261023/evidence/failure_and_fix.json)保留。

## 4. 包含在线识别成本的完整窗口结果

三次新进程CPU中位数，关闭完整日志；检测、失效、回退均计费。

| 配置/模式 | 循环CPU | 循环加速 | 整进程加速 |
|---|---:|---:|---:|
| 独立reference | 1.0015 s | 1.00× | 1.00× |
| 独立incremental | 0.6905 s | 1.45× | 1.38× |
| 独立bank_rowhit | 0.7088 s | 1.41× | 1.35× |
| 独立bank_hybrid | 0.6535 s | **1.53×** | **1.45×** |
| 共享reference | 2.4874 s | 1.00× | 1.00× |
| 共享incremental | 1.6733 s | 1.49× | 1.46× |
| 共享bank_rowhit | 2.0808 s | 1.20× | 1.18× |
| 共享bank_hybrid | 1.6259 s | **1.53×** | **1.49×** |

共享组合相对incremental额外加速约2.9%，不支持“符号方法已大幅超越增量”。不同配置不是
硬件性能对比，不同轮次reference绝对时间也不能互相缩放。

| 配置 | 固定步长READ覆盖 | 时序投影READ覆盖 | 投影平均段长（长度≥2） |
|---|---:|---:|---:|
| 独立TSV | 60.02% | 61.20% | 3.39 |
| 共享总线 | 33.84% | 34.16% | 28.13 |

分母是accepted READ请求，分子是实际执行的长度≥2计划READ，既非同row比例也非CPU份额。
部分共享READ由原控制器write-forwarding完成，没有发DRAM RD。共享投影覆盖与固定步长
接近，但平均段长从2.83增至28.13，减少重复识别成本。

负结果：独立高压到达中hybrid约0.55× reference，明显输给增量。它仍过度撤销本地计划；
不能全局默认启用，后续需要精确失效范围与成本守卫。[完整测量](../results/interference_20261023/MEASUREMENTS.md)。

## 5. 固定顺序图的诊断结论

C获得参考命令/入pending次序、接纳、刷新注入及队列策略分支。实际发射/完成周期仅在
expected数组中；release来自接纳、刷新或有因果来源的队列阶段约束。没有预测顺序，不能
作为在线加速。共享窗口有471,344个命令＋224,896个callback节点：

| 图模型 | 命令周期错误 | callback周期错误 |
|---|---:|---:|
| 物理timing＋顺序，缺策略依赖 | 1,384 | 0 |
| 加入队列阶段依赖 | **0** | **0** |
| 故意漏掉共享数据总线 | 448,812 | 220,788 |

只看最终callback会漏掉第一行。物理约束只是下界，控制器会因队列阈值选择等待。
完整图696,240节点、2,775,947边，7次遍历中位数约4.18 ms；Python建图约5.22 s、CSR导出
约0.012 s。**冷建图还比reference慢**，不能报告数百倍端到端加速。

将expected全部加17后，预测文件仍逐字节相同，全部节点按预期报错。
[图诊断](../results/interference_20261023/evidence/graph_shared_full_ablation_v2/results.json)、
[扰动检查](../results/interference_20261023/evidence/expected_poison_check/result.json)。

## 6. 整理、复现与边界

C++移至`native/`，IO/执行和workload抽至公共模块，区分在线实验、oracle、checker与历史入口。
八种旧合成输入不变；整理后重编译二进制与本轮测量逐字节相同，另4个case/12次比较通过。
旧`run.py`入口另跑A类1万请求，四条执行路径的事件与状态差分也通过；单次计时不纳入性能表。
[最终构建校验](../results/interference_20261023/evidence/cleanup_final_identity.json)、
[旧入口回归](../results/interference_20261023/evidence/legacy_cleanup_control/results.json)。
原始运行位于`/Orion/jian/jhn/dram-fast-forward/runs/interference_001`；大trace/CSR留在服务器，
Git只保存小型证据、SHA和复现代码。完整命令见仓库README。

现在应继续研究低成本依赖发现、按资源安排事件和混合命令区域。通用JEDEC/控制器、低成本
全图编译、完整加速器闭环以及所有负载不退化，仍未解决；不由1.5×或毫秒图遍历推断已完成。
