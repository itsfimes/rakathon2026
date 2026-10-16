export type Decoder<T> = (value: unknown) => T
export function invalid(): never { throw new Error('Invalid backend response') }
export const text: Decoder<string> = value => typeof value === 'string' && value.length <= 4096 ? value : invalid()
export const number: Decoder<number> = value => typeof value === 'number' && Number.isFinite(value) ? value : invalid()
export const boolean: Decoder<boolean> = value => typeof value === 'boolean' ? value : invalid()
export const id: Decoder<string> = value => /^[A-Za-z0-9.-]{1,64}$/.test(text(value)) ? text(value) : invalid()
export const reference: Decoder<string> = value => /^(Patient|Observation|DiagnosticReport|Practitioner|Organization)\/[A-Za-z0-9.-]{1,64}$/.test(text(value)) ? text(value) : invalid()
export const literal = <T extends string | number | boolean>(expected: T): Decoder<T> => value => value === expected ? expected : invalid()
export const nullable = <T>(decode: Decoder<T>): Decoder<T | null> => value => value === null ? null : decode(value)
export const array = <T>(decode: Decoder<T>): Decoder<T[]> => value => Array.isArray(value) && value.length <= 50 ? value.map(decode) : invalid()
export function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid()
  return value as Record<string, unknown>
}
type Decoded<S> = { [K in keyof S]?: S[K] extends Decoder<infer T> ? T : never }
/** Reconstruct only explicitly allowed keys; this assertion never casts an input DTO. */
export function fields<S extends Record<string, Decoder<unknown>>>(schema: S): Decoder<Decoded<S>> {
  return value => {
    const input = object(value)
    const output: Record<string, unknown> = {}
    for (const [key, decode] of Object.entries(schema)) if (Object.hasOwn(input, key)) output[key] = decode(input[key])
    return output as Decoded<S>
  }
}
export const coding = fields({ system: text, version: text, code: text, display: text })
export const concept = fields({ coding: array(coding), text })
export const ref = fields({ reference, display: text })
export const period = fields({ start: text, end: text })
export const quantity = fields({ value: number, unit: text, system: text, code: text })
const range = fields({ low: quantity, high: quantity })
const values = { valueQuantity: quantity, valueCodeableConcept: concept, valueString: text, valueBoolean: boolean, valueInteger: number,
  valueRange: range, valueRatio: fields({ numerator: quantity, denominator: quantity }) }
const referenceRange = fields({ low: quantity, high: quantity, type: concept, text, age: range })
const attachment = fields({ contentType: text, title: text, creation: text })
const base = { resourceType: text, id, meta: fields({ versionId: text, lastUpdated: text, source: text }) }
export const patient = fields({ ...base,
  name: array(fields({ use: text, text, family: text, given: array(text), prefix: array(text), suffix: array(text) })),
  birthDate: text, gender: text, active: boolean,
  telecom: array(fields({ system: text, value: text, use: text })),
  address: array(fields({ use: text, type: text, text, line: array(text), city: text, district: text, state: text, postalCode: text, country: text })),
})
export const condition = fields({ ...base, clinicalStatus: concept, verificationStatus: concept, category: array(concept), severity: concept,
  code: concept, bodySite: array(concept), subject: ref, onsetDateTime: text, onsetPeriod: period, abatementDateTime: text,
  recordedDate: text, recorder: ref, asserter: ref, evidence: array(fields({ code: array(concept), detail: array(ref) })),
})
export const observationValue = fields({ ...values, code: concept, interpretation: array(concept), referenceRange: array(referenceRange) })
export const observation = fields({ ...base, ...values, status: text, category: array(concept), code: concept, subject: ref,
  effectiveDateTime: text, effectivePeriod: period, issued: text, interpretation: array(concept), referenceRange: array(referenceRange),
  dataAbsentReason: concept, component: array(observationValue),
})
export const report = fields({ ...base, status: text, category: array(concept), code: concept, subject: ref,
  effectiveDateTime: text, effectivePeriod: period, issued: text, result: array(ref), conclusion: text, conclusionCode: array(concept), presentedForm: array(attachment),
})
export const document = fields({ ...base, status: text, docStatus: text, type: concept, category: array(concept), subject: ref,
  date: text, description: text, author: array(ref), content: array(fields({ attachment, format: coding })), context: fields({ period }),
})
export type Patient = ReturnType<typeof patient>
export type Condition = ReturnType<typeof condition>
export type Observation = ReturnType<typeof observation>
export type Report = ReturnType<typeof report>
export type Document = ReturnType<typeof document>
export type Concept = ReturnType<typeof concept>
export type Quantity = ReturnType<typeof quantity>
export type ObservationValue = ReturnType<typeof observationValue>
