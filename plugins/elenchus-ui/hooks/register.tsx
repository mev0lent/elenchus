import type { Register, Hook } from 'claude-code'

import { PALETTE, TONES, parse, view, sessionStatePath } from './palette'

async function current($: Parameters<Hook<'session.start'>>[0]) {
    const id = await $.session.id()
    let root = (await $.session.root()).replace(/\\/g, '/').replace(/\/$/, '')
    for (let i = 0; i < 30; i++) {
      const path = sessionStatePath(root, id)
      const text = await $.fs.read(path).catch(() => '')
      if (text !== '') return { path, state: parse(text), text }
      if (await $.fs.stat(`${root}/.elenchus`).then(() => true, () => false)) {
        return { path, state: null, text: '' }
      }
      const parent = root.replace(/\/[^/]+$/, '')
      if (parent === root || parent === '' || /^[A-Za-z]:$/.test(parent)) break
      root = parent
    }
    return { path: sessionStatePath(root, id), state: null, text: '' }
}

// A persistent focus card beside the input. UI never changes gate state.
export const register: Register = on => {
  let stamp = ''
  let poll: { cancel: () => void } | undefined
  const compactCalls = new Set<string>()

  on('session.start', async ($, e, next) => {
    poll?.cancel()
    poll = $.clock.every(1000, async () => {
      const now = await current($)
      const signature = `${now.path}:${now.text}`
      if (signature !== stamp) {
        stamp = signature
        $.ui.invalidate('ui.render')
      }
    })
    return next(e)
  })

  on('session.end', async ($, e, next) => {
    // /clear and /resume reuse the process without another session.start.
    if (e.reason !== 'clear' && e.reason !== 'resume') {
      poll?.cancel()
      poll = undefined
    }
    compactCalls.clear()
    stamp = ''
    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const { state } = await current($)
    const v = state && view(state)
    if (!v || e.props.hasSurvey) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const tone = TONES[v.tone]
    const compact = e.props.bodyColumns < 60 || e.props.maxRows < 7

    return (
      <Box flexDirection="column">
        {await next(e)}
        <Box flexDirection="column" backgroundColor={PALETTE.navy} borderStyle="round" borderColor={tone.bg} paddingX={1}>
          <Box>
            <Text backgroundColor={tone.bg} color={tone.fg} bold>{` ${tone.label} `}</Text>
            <Text color={PALETTE.cream} bold wrap="truncate-end">{` Elenchus · ${v.topic || v.mode}`}</Text>
            {!compact && v.rounds !== '' ? <Text color={PALETTE.teal}>{` · ${v.rounds}`}</Text> : null}
          </Box>
          {v.question !== '' ? <Text color={PALETTE.cream} bold>{v.question}</Text> : null}
          <Text color={PALETTE.teal}>{v.hint}</Text>
          {!compact ? <Text color={PALETTE.cream}>{`${v.mode}${v.support ? ` · ${v.support}` : ''} · /elenchus:focus full shows tool details`}</Text> : null}
          {v.violations > 0 ? <Text backgroundColor={PALETTE.crimson} color={PALETTE.cream}>{` Rule violations: ${v.violations} · /elenchus:status`}</Text> : null}
        </Box>
      </Box>
    )
  })

  on('ui.render', { component: 'ToolUse' }, async ($, e, next) => {
    const { state } = await current($)
    if (!state?.active || state.ui_details || e.props.isErrored || e.props.isInterrupted) return next(e)
    const input = e.props.input as { command?: string } | null
    const command = typeof input?.command === 'string' ? input.command : ''
    const internal = /(?:^|[/'"\\])elenchus\.py['"]?\s+(?:--session\s+(?:"[^"]+"|'[^']+'|\S+)\s+)?(gate|challenge|verdict|assess|prepare|question|status|cards)\b/.exec(command)
    if (!internal || !['Bash', 'PowerShell'].includes(e.props.tool)) return next(e)
    compactCalls.add(e.props.tool_use_id)
    const { Text } = $.ui.resolve(e)
    return <Text color={PALETTE.teal}>{`Elenchus · ${internal[1]}${e.props.isRunning ? ' …' : ' ✓'}`}</Text>
  })

  on('ui.render', { component: 'ToolResult' }, async ($, e, next) => {
    const { state } = await current($)
    if (!state?.active || state.ui_details || e.props.isErrored || !compactCalls.has(e.props.tool_use_id)) return next(e)
    const { Box } = $.ui.resolve(e)
    return <Box />
  })
}
