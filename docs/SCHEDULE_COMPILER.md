# 调度区域编译：第一阶段合同与实现

本分支把incremental/hybrid作为对照。输入是模拟前的Tile/DMA循环与静态DRAM语义，输出是
可审查的条件证书和专用C++时序/状态代码。编译器不读取oracle命令、策略日志或完成时间。

## 输入和三步实现

1. `extract_dma_ir.py`读取真实`upgate/tile0`的长度前缀JSON描述。两个读取范围为
   `[base,width,rows,stride]`，地址为`base+r*stride+256*l`。使用系统现有libisl对整数关系
   做投影与等价检查，不需要安装islpy或新建环境。
2. `schedule_compile.py`从共享/私有timing边与已声明的ready-then-oldest控制器语义，
   实例化一个受限调度区域证明规则，输出守卫、递推和终态赋值。READ/WRITE使用同一规则。
3. `compiler_adapter.hh`绑定运行中的队列与物理状态。支持区间直接调用生成的时序/状态代码；
   原接纳、回压、pending FIFO、回调、刷新与不支持的区域继续按冻结语义执行。

这里是**受限语义片段的部分求值原型**。证明规则库、控制器语义及ABI仍由人定义；尚未从任意
控制器C++自动合成调度守卫，也未实现通用多面体调度编译器。生成头文件不是手写fast-path的
复制，但代码生成这一事实本身也不足以构成新的论文贡献。

## 资源表示

共享fixture中：

\[
a(r,l)=base+r\,stride+256l,
\quad Bank=\lfloor a/1024\rfloor\bmod8,
\quad Row=\lfloor a/8192\rfloor.
\]

实际权重DMA为width4096、rows128、stride16384。对参数化行数R及`base=8192B`，isl证明
Bank投影为`floor(l/4) mod 8`，不依赖r；Row仍随r变化。编译器保留这一Row关系，不据Bank
周期相同假定每次都是row hit。该证明不需要展开128行，更不需要先运行DRAM模拟。

生成的资源周期可支持不同循环次数、入口时刻和合法open-row状态。运行时adapter还需核对
队列与资源模式是否一致；当前尚未通过受信任的结构化producer接口消除这次队列扫描。

## 时序规则与条件

支持的一个区域内，最终命令c相同且不改变row状态；共享与私有的c→c约束窗口为1，没有
sibling或blocked-offset副作用。设共享间隔Δ不小于各私有间隔，入口共享就绪为S，bank就绪
为Rb，候选队列最老请求位于b0，首次出现bank b的位置为pb：

\[
f=\max(now+1,S,R_{b0}).
\]

自动实例化的条件为：对所有出现的bank，

\[
\max(now+1,S,R_b)\ge f,
\qquad R_b\le f+p_b\Delta.
\]

第一条保证没有更年轻请求能早于最老请求发射。第一次发射后，共享资源使任何同类请求在
`f+iΔ`之前均不可发射；第二条保证到该时刻，最老候选确实ready。已访问bank的约束通过
私有间隔≤共享间隔归纳得到。因此FIFO在此条件域中成立，生成：

\[
t_i=f+i\Delta.
\]

isl对首次访问、后续私有递推和共享排他三条归纳步骤检查整数反例集合为空；这不是整个
控制器与回调实现的形式化验证。后者由ABI边界分析和逐事件/状态差分共同检查。

命令终态按每个物理资源最后一次发射更新。所有相关timing均为window1，ready更新是单调max，
因此可折叠中间赋值；共享channel使用全区域最后命令，bank分别使用自己的最后命令。
编译器由timing表生成具体更新，执行时不解释timing边表。

## 动态边界

- active或maintenance非空：不进入该区域。
- 读写水位可能改变选择：截断区域或回退；混合RD/WR仍未编译成同一个区域。
- 新请求：只有已发射后的同类row-hit、且FCFS年龄较晚时可保留旧前缀；其余先物化再回退。
- 刷新：跳时即将到达刷新拍时先退出，保持同拍的刷新优先级。
- callback：保留每条实际回调和pending FIFO顺序；闭环新增请求在原接口边界送入。
- 跨Row的PRE/ACT和四ACT窗口目前由原精确路径执行，不能算作已编译覆盖。

事件推进在各domain之间取下一条必要命令、callback、外部到达、刷新及观察点的最小值。
有N个独立回调时仍需O(N)输出；减少的是内部重复调度、timing解释和无事件周期。

## 必须保留的对照

| 路径 | 目的 |
|---|---|
| reference / incremental / event / bank_hybrid | 同物理定义下的原有基线 |
| compiled_stride | 同生成时序内核，取最长正stride或重复地址RLE前缀 |
| compiled_resource | 加入编译得到的Bank周期投影 |
| compiled_dynamic | 同生成时序内核，从当前队列直接分组资源，不要求多面体模式 |

最后一个对照特别重要：本证明规则可能仅需资源分类。若它与多面体方案相同或更快，结果
只能支持编译后的时序求值，不能证明多面体前端是收益来源。简单stride/RLE对照也不是所有
非多面体编译方法的最强上界。

## 成本与证据范围

报告提取/isl证明、生成代码、C++构建和执行时间。当前构建会重新编译整个包含物理模型的
translation unit；报告完整构建成本，不能把它省略，也不假装已有增量插件编译。

若编译总CPU成本为C，hybrid与生成路径每次整进程CPU分别为H、G，则仅在H>G时有：

\[
N_{break-even}=\lceil C/(H-G)\rceil.
\]

真实tile测试使用模拟前的DMA描述，并明确规定到达模型；历史完整E请求窗口只作兼容性
回放。其到达时刻来自原捕获，不能代替结构化加速器闭环或算成编译输入中的调度知识。

## 相关工作的具体边界

[Warping](https://arxiv.org/abs/2203.14845)将多面体访问与状态对应条件结合，研究Cache跳跃；
这里借鉴其条件化证明思路，不能继承Cache结论来证明动态DRAM调度。
[LightningSimV2](https://arxiv.org/abs/2404.09471)用静态分析及图构建/求值分离减少仿真冗余；
其图编译和DSE收益不作为本实验的速度证据。
[isl官方手册](https://libisl.sourceforge.io/user.html)提供整数集、关系及精确投影/等价操作；
本原型使用这些操作验证资源关系和受限归纳条件，尚未使用完整schedule-tree生成设施。

下一阶段是否继续多面体主线，应由上述强对照决定。更有价值的待解问题是含PRE/ACT、
读写阶段及有限动态到达的混合命令区域，和从结构化producer接口免去反复队列扫描。
