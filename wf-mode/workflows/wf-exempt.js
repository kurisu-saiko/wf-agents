export const meta = {
  name: 'wf-exempt',
  description: '显式指定管线：跳过规则路由，直接执行一次',
  phases: [{ title: '执行', detail: '按指定管线完成取证、账本与结论' }],
}

const PIPELINES = {
  'wf-retrieval': 'wf-retrieval',
  'wf-project-eval': 'wf-project-eval',
  'wf-project-reading': 'wf-project-reading',
}

function parseArgs(value) {
  let task = ''
  let runDir = ''
  let pipeline = ''
  if (value && typeof value === 'object') {
    task = String(value.task || value.input || value.prompt || '').trim()
    runDir = String(value.runDir || '')
    pipeline = String(value.pipeline || value.route || '').trim()
    return { task, runDir, pipeline }
  }
  if (typeof value === 'string') {
    const s = value.trim()
    if (s.startsWith('{')) {
      try {
        const obj = JSON.parse(s)
        if (obj && typeof obj === 'object') {
          return {
            task: String(obj.task || obj.input || obj.prompt || '').trim(),
            runDir: String(obj.runDir || ''),
            pipeline: String(obj.pipeline || obj.route || '').trim(),
          }
        }
      } catch {
        // 按普通文本处理
      }
    }
    const m = s.match(/^[@]?(wf-[a-z0-9-]+)\s*[:：]?\s*([\s\S]*)$/i)
    if (m) return { pipeline: m[1].toLowerCase(), task: m[2].trim(), runDir: '' }
    return { task: s, runDir: '', pipeline: '' }
  }
  return { task: '', runDir: '', pipeline: '' }
}

function fallbackRunDir(task) {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  const ts = `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
  const slug = String(task).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 24)
  return `.wf/runs/${ts}-${slug || 'task'}`
}

const input = parseArgs(args)

if (!input.task) {
  return {
    status: 'no_input',
    message: 'wf-exempt 需要任务文本。用法：/wf @wf-retrieval <任务>。',
  }
}

// launch.ps1 会根据任务前缀选择 wf-exempt，但 args 里不一定带 pipeline；从原任务前缀兜底解析。
let pipeline = input.pipeline
let body = input.task
if (!pipeline) {
  const m = String(input.task).match(/^[@]?(wf-[a-z0-9-]+)\s*[:：]?\s*([\s\S]*)$/i)
  if (m) {
    pipeline = m[1].toLowerCase()
    body = m[2].trim()
  }
}

if (!Object.prototype.hasOwnProperty.call(PIPELINES, pipeline)) {
  return {
    status: 'invalid_pipeline',
    pipeline,
    task: input.task,
    message: '需要指定合法管线：wf-retrieval / wf-project-eval / wf-project-reading。',
  }
}

const runDir = (input.runDir || fallbackRunDir(body)).replace(/\\/g, '/')

phase('执行')

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
  mode: 'exempt',
  task: body,
  pipeline,
  runDir,
  deliverable: String(deliverable || ''),
}
