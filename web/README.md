# Pipeline UI prototype

This dependency-free web prototype visualises the current Granite Voice
Concierge pipeline and follows the shapes in
`docs/app-pipeline-ui-contract.md`.

Run it from the repository root:

```bash
python -m http.server 4173 --directory web
```

Then open `http://localhost:4173`.

## Integration boundary

`app.js` currently uses a deterministic in-browser demo adapter so the turn
flow, confirmations, error fallback, and persistent state can be reviewed before
the app pipeline exists. Replace `buildResponse(transcript)` with a backend call
that sends:

```js
{
  transcript,
  state: state.pipeline,
  options: { synthesize: false, play: false }
}
```

The UI intentionally stores and returns the complete `response.state` object on
every turn. Wake word and VAD are shown as bypassed for web transcript input;
they remain visible in the inspector because they are part of the complete
voice pipeline.
