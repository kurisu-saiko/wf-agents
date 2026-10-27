export const meta = {
  name: 'wf-research',
  description: '信息搜集：显式指定 → 模型解读 → 规则兜底 → 单趟闭环管线',
  phases: [
    { title: '路由', detail: '显式指定优先；模型解读整理与转接；失败才走规则' },
    { title: '执行', detail: '按管线规范完成取证、账本与结论' },
  ],
}

// ---------------------------------------------------------------- 常量

const PIPELINES = {
  'wf-retrieval': 'wf-retrieval',
  'wf-project-eval': 'wf-project-eval',
  'wf-project-reading': 'wf-project-reading',
}

// 规则表是数据，也是模型解读层失效时的兜底；只按交付物特征匹配。
const RULES = {
  'wf-retrieval': [
    '核实', '查证', '是否属实', '出处', '来源', '官方', '文档', '版本',
    '兼容', '事实', '确认一下', '引用', '原文',
  ],
  'wf-project-eval': [
    '值不值得', '能不能用', '可否采用', '采用', '选哪', '选择哪', '哪个项目',
    '替代', '技术选型', '自建', '对比', '评估', '开源项目', '推荐一个',
  ],
  'wf-project-reading': [
    '怎么跑', '怎么运行', '架构', '目录结构', '入口', '主流程', '数据流',
    '代码库', '仓库结构', '模块', '启动流程', '这个仓库', '本地项目',
  ],
}

// ---------------------------------------------------------------- 输入 / 解析

function parseArgs(value) {
  if (value && typeof value === 'object') {
    return { task: String(value.task || value.input || value.prompt || '').trim(), runDir: String(value.runDir || '') }
  }
  if (typeof value === 'string') {
    const s = value.trim()
    if (s.startsWith('{')) {
      try {
        const obj = JSON.parse(s)
        if (obj && typeof obj === 'object') {
          return { task: String(obj.task || obj.input || obj.prompt || '').trim(), runDir: String(obj.runDir || '') }
        }
      } catch {
        // 不是 JSON，按普通任务文本处理
      }
    }
    return { task: s, runDir: '' }
  }
  return { task: '', runDir: '' }
}

function splitExplicit(task) {
  const m = String(task).match(/^[@]?(wf-[a-z0-9-]+)\s*[:：]?\s*([\s\S]*)$/i)
  if (!m) return null
  return { pipeline: m[1].toLowerCase(), rest: m[2].trim() }
}

function classify(task) {
  const text = String(task)
  const hits = {}
  for (const [pipeline, words] of Object.entries(RULES)) {
    const matched = words.filter((w) => text.includes(w))
    if (matched.length) hits[pipeline] = matched
  }
  return hits
}

function parseJson(text) {
  if (!text || typeof text !== 'string') return null
  let s = text.trim()
  const fence = s.match(/```(?:json)?\s*([\s\S]*?)```/i)
  if (fence) s = fence[1].trim()
  const start = s.indexOf('{')
  const end = s.lastIndexOf('}')
  if (start < 0 || end <= start) return null
  try {
    return JSON.parse(s.slice(start, end + 1))
  } catch {
    return null
  }
}

function validInterpretation(plan) {
  if (!plan || typeof plan !== 'object') return false
  if (plan.status === 'out_of_domain' || plan.status === 'needs_clarification') return true
  if (plan.status !== 'ok') return false
  if (!Object.prototype.hasOwnProperty.call(PIPELINES, plan.pipeline)) return false
  return typeof plan.refinedTask === 'string' && plan.refinedTask.trim().length > 0
}

function fallbackRunDir(task) {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  const ts = `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
  const slug = String(task).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 24)
  return `.wf/runs/${ts}-${slug || 'task'}`
}

async function interpretTask(raw) {
  try {
    const out = await agent(
      [
        '你是任务解读层，只做逻辑整理与管线转接。',
        '',
        '用户原始任务：',
        '"""',
        raw,
        '"""',
        '',
        '按你的规范输出一段合法 JSON，不要解释，不要代码围栏。',
      ].join('\n'),
      { agentType: 'wf-task-interpret', label: 'interpret', phase: '路由' },
    )
    return parseJson(out)
  } catch {
    return null
  }
}

// ---------------------------------------------------------------- 主流程

const input = parseArgs(args)
const task = input.task

if (!task) {
  return {
    status: 'no_input',
    message: 'wf-research 需要任务文本。用法：/wf <任务> 或 /wf @wf-retrieval <任务>。',
  }
}

const runDir = (input.runDir || fallbackRunDir(task)).replace(/\\/g, '/')

phase('路由')

let pipeline = ''
let route = ''
let body = task
let planForExecution = null

const explicit = splitExplicit(task)

if (explicit) {
  if (!Object.prototype.hasOwnProperty.call(PIPELINES, explicit.pipeline)) {
    return {
      status: 'invalid_pipeline',
      task,
      pipeline: explicit.pipeline,
      message: '只允许：wf-retrieval / wf-project-eval / wf-project-reading。',
    }
  }
  if (!explicit.rest) {
    return {
      status: 'no_input',
      message: '显式指定管线时还需要任务文本。',
    }
  }
  pipeline = PIPELINES[explicit.pipeline]
  route = 'explicit'
  body = explicit.rest
} else {
  const interpretation = await interpretTask(task)

  if (validInterpretation(interpretation)) {
    if (interpretation.status === 'out_of_domain') {
      return {
        status: 'out_of_domain',
        task,
        reason: interpretation.reason || '不属于信息搜集范围。',
      }
    }

    if (interpretation.status === 'needs_clarification') {
      return {
        status: 'needs_clarification',
        task,
        question: interpretation.question || '需要补充信息才能选择管线。',
        options: Array.isArray(interpretation.options) ? interpretation.options : [
          'wf-retrieval：核实事实、给出处',
          'wf-project-eval：判断项目能否采用、做选型',
          'wf-project-reading：读懂本地代码库的架构与运行方式',
        ],
      }
    }

    pipeline = PIPELINES[interpretation.pipeline]
    route = 'model'
    body = interpretation.refinedTask.trim()
    planForExecution = interpretation
  } else {
    // 模型解读层不可解析或不合格 → 退回确定性规则。
    const hits = classify(task)
    const matched = Object.keys(hits)
    if (matched.length === 1) {
      pipeline = PIPELINES[matched[0]]
      route = `rule:${hits[matched[0]].join(',')}`
    } else {
      return {
        status: 'needs_clarification',
        task,
        question: matched.length
          ? '任务同时命中多条管线，需要你指定一条。'
          : '模型解读与规则都未能唯一判断该走哪条管线，需要你指定一条。',
        options: [
          'wf-retrieval：核实事实、给出处',
          'wf-project-eval：判断项目能否采用、做选型',
          'wf-project-reading：读懂本地代码库的架构与运行方式',
        ],
      }
    }
  }
}

phase('执行')

const planLines = planForExecution
  ? [
      '模型解读层给出的计划：',
      JSON.stringify(
        {
          slots: planForExecution.slots || {},
          deliverable: planForExecution.deliverable || '',
          acceptance: planForExecution.acceptance || [],
          excluded: planForExecution.excluded || [],
        },
        null,
        2,
      ),
      '',
    ]
  : []

const deliverable = await agent(
  [
    `你是执行级管线 ${pipeline}。`,
    '',
    `本次运行账本目录：${runDir}`,
    '',
    '硬性要求：',
    '1. 只允许写该目录下的 run.json / evidence.json / result.md 三个文件，禁止写其它路径。',
    '2. 先完成账本，再写结论；结论中的每条断言必须能在 evidence.json 中找到对应条目。',
    '3. 工具优先级：优先封装工具；封装通道不可用时按降级阶梯退到底层命令，并写进 run.json 的 degradation。',
    '4. 只做本管线允许的事，不越界。',
    '',
    ...planLines,
    '用户任务：',
    '"""',
    body,
    '"""',
    '',
    '按你的管线规范执行，最终回复只输出 result.md 的内容。',
    '最终回复使用用户任务的语言；默认中文。账本字段值也用同一语言。',
  ].join('\n'),
  { agentType: PIPELINES[pipeline], label: pipeline, phase: '执行' },
)

return {
  status: 'ok',
  task: body,
  pipeline,
  route,
  runDir,
  plan: planForExecution,
  deliverable: String(deliverable || ''),
}
