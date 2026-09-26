import { describe, expect, it } from 'vitest'

import {
  normalizeNunmaiOpenString,
  pathFromNunmaiDeepLink,
  pathFromOpenDeepLink,
  resolveNunmaiOpenPath
} from './nunmai-open-target'

describe('normalizeNunmaiOpenString', () => {
  it('accepts hash-router paths and strips a leading hash', () => {
    expect(normalizeNunmaiOpenString('/index-network/intent/1')).toBe('/index-network/intent/1')
    expect(normalizeNunmaiOpenString('#/index-network/intent/1')).toBe('/index-network/intent/1')
  })

  it('maps plugin-scoped nunmai:// deep links to the same path', () => {
    expect(normalizeNunmaiOpenString('nunmai://index-network/intent/1')).toBe('/index-network/intent/1')
    expect(normalizeNunmaiOpenString('nunmai://index-network/intent/1?focus=true')).toBe(
      '/index-network/intent/1?focus=true'
    )
  })

  it('maps nunmai://open/… deep links by stripping the open host', () => {
    expect(normalizeNunmaiOpenString('nunmai://open/index-network/intent/1')).toBe('/index-network/intent/1')
    expect(normalizeNunmaiOpenString('nunmai://open/settings/plugins')).toBe('/settings/plugins')
  })

  it('rejects reserved nunmai kinds and unsafe paths', () => {
    expect(normalizeNunmaiOpenString('nunmai://blueprint/morning-brief')).toBeNull()
    expect(normalizeNunmaiOpenString('nunmai://plugin/install')).toBeNull()
    expect(normalizeNunmaiOpenString('https://example.com/x')).toBeNull()
    expect(normalizeNunmaiOpenString('/../etc/passwd')).toBeNull()
    expect(normalizeNunmaiOpenString('index-network')).toBeNull()
  })
})

describe('resolveNunmaiOpenPath', () => {
  it('merges structured path + params', () => {
    expect(resolveNunmaiOpenPath({ path: '/index-network/intent/1', params: { focus: 'true' } })).toBe(
      '/index-network/intent/1?focus=true'
    )
  })

  it('resolves href the same as a bare string', () => {
    expect(resolveNunmaiOpenPath({ href: 'nunmai://index-network/intent/1' })).toBe('/index-network/intent/1')
  })
})

describe('pathFromNunmaiDeepLink', () => {
  it('builds the navigate path from a plugin-scoped deep-link payload', () => {
    expect(pathFromNunmaiDeepLink('index-network', 'intent/1')).toBe('/index-network/intent/1')
  })

  it('builds the navigate path from nunmai://open/… payloads', () => {
    expect(pathFromOpenDeepLink('index-network/intent/1')).toBe('/index-network/intent/1')
    expect(pathFromNunmaiDeepLink('open', 'agent/42')).toBe('/agent/42')
  })

  it('ignores reserved kinds', () => {
    expect(pathFromNunmaiDeepLink('blueprint', 'morning-brief')).toBeNull()
    expect(pathFromNunmaiDeepLink('plugin', 'install')).toBeNull()
  })
})
