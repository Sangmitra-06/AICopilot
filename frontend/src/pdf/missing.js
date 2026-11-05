// Did loading the PDF fail because the file is gone (the server answered 404)? pdf.js reports that as a
// MissingPDFException; a bare status is accepted too.
export const isMissingPdf = err => Boolean(err) && (err.name === 'MissingPDFException' || err.status === 404)
