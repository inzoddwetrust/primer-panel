// The one way a path of the API is made of anything that is not written in
// the page's own source (DM-210, PRIMER-PANEL-REVIEW-0001): a parameter of the
// page's address, an id an answer of the API gave.
//
//   apiPath`/api/v1/servers/${props.serverId}/runs/${props.runId}`
//
// Every substitution is one segment of a path and nothing else: letters,
// digits and `. _ : -` (a UUID, a run's id `2026-11-25T10:00:00Z-a3f9`), and
// neither `.` nor `..`. Anything else -- a `/`, a `?`, a `#`, a `%`, an empty
// text, a value that is no text -- is refused: the function throws
// PathSegmentError, the screen shows it, no request leaves.
//
// Refused, not encoded. Measured on the Panel's backend: it decodes a path
// before it finds the route, so `/api/v1/servers/<id>%2Fkey-wait` is answered
// by the handler of `/api/v1/servers/<id>/key-wait` -- an encoded `/` in a
// parameter still reaches the neighbouring handler under the page's Origin.
// The router is the first line (src/router.ts: a parameter off its form is no
// page of the Panel); this is the second, for whatever reaches a screen by
// another way.
//
// A path made here may be the start of another: an ApiPath is put in as it
// is. src/api/paths.spec.ts keeps every other template with a `/` and a
// substitution out of src/.

const SEGMENT = /^[A-Za-z0-9._:-]+$/

export class PathSegmentError extends Error {
  constructor(readonly given: unknown) {
    super('a part of an address of the API that is not one segment')
    this.name = 'PathSegmentError'
  }
}

export class ApiPath {
  constructor(private readonly text: string) {}

  toString(): string {
    return this.text
  }
}

export function segment(value: unknown): string {
  if (typeof value !== 'string' || !SEGMENT.test(value) || value === '.' || value === '..') {
    throw new PathSegmentError(value)
  }
  return value
}

export function apiPath(strings: TemplateStringsArray, ...values: unknown[]): ApiPath {
  let path = strings[0] ?? ''
  values.forEach((value, index) => {
    path += value instanceof ApiPath ? value.toString() : segment(value)
    path += strings[index + 1] ?? ''
  })
  return new ApiPath(path)
}
