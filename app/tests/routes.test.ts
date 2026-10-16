import { describe, expect, it } from 'vitest'
import { viewFromLocation } from '../src/lib/roles'
import { CLINICIAN_SECTIONS, detailSection, roleRoute, routeFromLocation, routeHref, routeKey, routesEqual, validCaseId } from '../src/lib/routes'
import type { Route } from '../src/lib/routes'

describe('canonical patient routes', () => {
  it.each(['koordinator', 'lekar', 'mdt'] as const)('%s has independent list/detail/invalid routes and role navigation always reaches list', view => {
    expect(routeFromLocation({ hash: `#${view}`, search: '?role=pacient' })).toEqual({ view, page: 'list' })
    expect(routeFromLocation({ hash: `#${view}/case/opaque%2Fid`, search: '?role=mdt' })).toEqual({ view, page: 'detail', caseId: 'opaque/id' })
    expect(roleRoute(view)).toEqual({ view, page: 'list' })
    expect(routeHref(roleRoute(view))).toBe(`#${view}`)
    expect(viewFromLocation({ hash: `#${view}/case/abc`, search: '?role=mdt' })).toBe(view)
  })

  it.each(['pacient', 'specimen'] as const)('%s remains an ordinary view route', view => {
    expect(routeFromLocation({ hash: `#${view}`, search: '?role=lekar' })).toEqual({ view, page: 'view' })
    expect(routeHref(roleRoute(view))).toBe(`#${view}`)
  })

  it.each(['', '#'])('empty hash %s uses allowlisted legacy role, never URL data mode', hash => {
    expect(routeFromLocation({ hash, search: '?role=lekar&mode=mock&source=mock&VITE_DATA_MODE=mock' })).toEqual({ view: 'lekar', page: 'list' })
    expect(routeFromLocation({ hash, search: '?role=unknown&mode=mock' })).toEqual({ view: 'koordinator', page: 'list' })
  })

  it.each(['#unknown', '#doctor/case/id', '#LEKAR', '#mode=mock'])('unknown route %s safely reaches coordinator list instead of query fallback', hash => {
    expect(routeFromLocation({ hash, search: '?role=mdt' })).toEqual({ view: 'koordinator', page: 'list' })
  })

  it.each(CLINICIAN_SECTIONS)('clinician section %s has canonical URLs, opaque IDs and complete route identity', section => {
    for (const view of ['koordinator', 'lekar'] as const) {
      const route: Route = { view, page: 'detail', caseId: 'opaque/id%2F', section }
      const href = routeHref(route)
      expect(href).toBe(`#${view}/case/opaque%2Fid%252F${section === 'overview' ? '' : `/${section}`}`)
      const parsed = routeFromLocation({ hash: href, search: '?role=mdt' })
      expect(parsed.page).toBe('detail')
      if (parsed.page !== 'detail') throw new Error('Expected detail')
      expect(detailSection(parsed)).toBe(section)
      expect(routesEqual(parsed, route)).toBe(true)
      expect(routeKey(parsed)).toBe(routeKey(route))
      if (section !== 'overview') expect(routesEqual(parsed, { view, page: 'detail', caseId: route.caseId })).toBe(false)
    }
  })

  it('explicit overview is an alias of the canonical base detail, not an extra history identity', () => {
    const parsed = routeFromLocation({ hash: '#lekar/case/opaque%2Fid/overview', search: '' })
    expect(parsed).toEqual({ view: 'lekar', page: 'detail', caseId: 'opaque/id' })
    expect(routeHref(parsed)).toBe('#lekar/case/opaque%2Fid')
  })

  it.each(['unknown', 'record/extra', '', 'record/', '%72ecord', 'care%00'])('unknown/malformed clinician section %s is invalid, never another case', section => {
    expect(routeFromLocation({ hash: `#lekar/case/id/${section}`, search: '?role=mdt' })).toEqual({ view: 'lekar', page: 'invalid-detail' })
  })

  it('patient record and case-specific MDT pages have safe role landing links', () => {
    for (const route of [{ view: 'pacient', page: 'record' }, { view: 'mdt', page: 'detail', caseId: 'novak' }, { view: 'mdt', page: 'detail', caseId: 'novak', section: 'plan' }] as const) {
      expect(routeFromLocation({ hash: routeHref(route), search: '?role=lekar&mode=mock' })).toEqual(route)
      expect(routesEqual(route, roleRoute(route.view))).toBe(false)
    }
    expect(routeHref(roleRoute('pacient'))).toBe('#pacient')
    expect(routeHref(roleRoute('mdt'))).toBe('#mdt')
  })

  it.each(['#pacient/case/id', '#pacient/plan', '#pacient/record/extra', '#pacient/', '#mdt/record', '#mdt/plan', '#mdt/plan/extra', '#specimen/unknown'])('recognized unknown section %s is explicitly invalid', hash => {
    const view = hash.slice(1).split('/')[0]
    expect(routeFromLocation({ hash, search: '?role=lekar' })).toEqual({ view, page: view === 'mdt' ? 'invalid-detail' : 'invalid-view' })
  })

  it.each(['/', '/case', '/case/', '/case/a/b', '/case/a/', '/other/id', '/case/%', '/case/%E0%A4%A', '/case/%00', '/case/a%0Ab', '/case/%7F', '/case/%C2%85', '/case/%20%20'])('recognized malformed detail suffix %s stays explicit invalid detail', suffix => {
    for (const view of ['koordinator', 'lekar'] as const) {
      expect(routeFromLocation({ hash: `#${view}${suffix}`, search: '?role=pacient' })).toEqual({ view, page: 'invalid-detail' })
    }
  })

  it.each(['unknown-backend-id', 'odd/id', 'literal%2Fid', 'Případ s mezerou', 'id?#&=+', 'emoji-🧪', ' colon: pipe| '])('round-trips opaque identifier %s, decoding only once', caseId => {
    const route: Route = { view: 'lekar', page: 'detail', caseId }
    const href = routeHref(route)
    expect(routeFromLocation({ hash: href, search: '' })).toEqual(route)
    expect(validCaseId(caseId)).toBe(true)
    expect(href).toBe(`#lekar/case/${encodeURIComponent(caseId)}`)
  })

  it('invalid programmatic identifiers yield a canonical invalid-detail URL rather than throwing', () => {
    for (const caseId of ['', ' ', '\u0000', '\ud800']) {
      expect(validCaseId(caseId)).toBe(false)
      expect(routeHref({ view: 'lekar', page: 'detail', caseId })).toBe('#lekar/case/')
    }
    expect(routeHref({ view: 'koordinator', page: 'invalid-detail' })).toBe('#koordinator/case/')
  })

  it('identity compares complete route, preserving delimiter-bearing opaque IDs', () => {
    const list = roleRoute('lekar')
    const first: Route = { view: 'lekar', page: 'detail', caseId: 'a|detail|b' }
    const second: Route = { view: 'lekar', page: 'detail', caseId: 'a' }
    expect(routesEqual(list, first)).toBe(false)
    expect(routesEqual(first, second)).toBe(false)
    expect(routesEqual(first, { ...first })).toBe(true)
    expect(new Set([routeKey(list), routeKey(first), routeKey(second), routeKey({ view: 'lekar', page: 'invalid-detail' })]).size).toBe(4)
  })
})
