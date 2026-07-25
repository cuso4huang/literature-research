# Literature Research Skill

[中文](#中文) · [English](#english)

## 中文

这是一个面向 Codex 的学术文献调研 Skill，通过 Semantic Scholar、OpenAlex、
Crossref 和 arXiv 完成可追溯的文献检索与综述。

它可以帮助智能体：

- 检索论文并逐步扩展关键词；
- 核验 DOI 与书目信息；
- 识别并关联预印本、会议论文和期刊版本；
- 综合主题相关性、方法匹配度、证据质量、时效性和引用信号进行排序；
- 归纳研究结论、分歧、局限与研究空白；
- 生成证据表和可用于引用的参考文献。

### 安装

克隆仓库：

```bash
git clone https://github.com/cuso4huang/literature-research.git
cd literature-research
```

将 `skills/literature-research` 复制到 Codex 的 Skills 目录：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/literature-research "${CODEX_HOME:-$HOME/.codex}/skills/"
```

安装后重启 Codex，并在提示词中显式调用：

```text
使用 $literature-research 检索并核验 AI 智能体评测领域的最新研究。
```

### 依赖

该 Skill 声明了 Semantic Scholar 和 arXiv MCP 工具依赖。附带的元数据核验脚本
通过 Crossref 与 OpenAlex 的公开 API 工作，需要 Python 3 和网络连接，不依赖
第三方 Python 包，也不需要 API Key。

可选设置 `OPENALEX_MAILTO` 环境变量，以便在请求 OpenAlex 时提供联系邮箱。

### 单独使用元数据核验脚本

进入 Skill 目录后运行：

```bash
cd skills/literature-research
python3 scripts/verify_metadata.py --doi "10.1145/..." --pretty
python3 scripts/verify_metadata.py --title "论文标题" --year 2024 --pretty
```

脚本会分别保留 Crossref 和 OpenAlex 返回的记录，并给出 `verified`、
`partially_verified`、`conflict` 或 `unverified` 核验状态。

## English

A Codex skill for traceable scholarly literature research across Semantic
Scholar, OpenAlex, Crossref, and arXiv.

It helps an agent:

- discover papers and expand search queries;
- verify DOI and bibliographic metadata;
- identify and connect preprints, conference papers, and journal versions;
- rank evidence by relevance, methodological fit, quality, recency, and
  citation signals;
- synthesize findings, disagreements, limitations, and research gaps;
- produce evidence tables and citation-ready references.

### Installation

Clone the repository:

```bash
git clone https://github.com/cuso4huang/literature-research.git
cd literature-research
```

Copy `skills/literature-research` into your Codex skills directory:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/literature-research "${CODEX_HOME:-$HOME/.codex}/skills/"
```

Restart Codex after installation, then invoke the skill explicitly:

```text
Use $literature-research to find and verify recent work on AI agent evaluation.
```

### Dependencies

The skill declares Semantic Scholar and arXiv MCP tool dependencies. Its
bundled metadata verifier uses the public Crossref and OpenAlex APIs and
requires Python 3 with network access. No third-party Python packages or API
keys are required.

You may optionally set `OPENALEX_MAILTO` to provide a contact email with
OpenAlex requests.

### Use the metadata verifier directly

From the skill directory, run:

```bash
cd skills/literature-research
python3 scripts/verify_metadata.py --doi "10.1145/..." --pretty
python3 scripts/verify_metadata.py --title "Paper title" --year 2024 --pretty
```

The script preserves the Crossref and OpenAlex records separately and reports
a `verified`, `partially_verified`, `conflict`, or `unverified` status.

## License

MIT
