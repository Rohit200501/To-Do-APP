# Do It

Double-click **Open TaskPilot.vbs** on Windows. It starts Do It as a native Windows window, without opening a browser or leaving a command window open. Closing the app window also stops the API. `Start TaskPilot.bat` is available if you want to see server messages.

Your tasks are stored only on this computer in `data/tasks.json`.

## Local API

The API accepts cross-origin requests so another webpage on your computer can call it.

- `GET /api/health` — confirm the service is running
- `GET /api/tasks` — list tasks
- `POST /api/tasks` — create a task
- `PATCH /api/tasks/{id}` — update a task, including `{ "completed": true }`
- `DELETE /api/tasks/{id}` — delete a task

Example create request:

```js
fetch('http://127.0.0.1:8787/api/tasks', {
  method: 'POST', headers: {'Content-Type':'application/json'},
  body: JSON.stringify({title:'Finish portfolio', category:'Project', priority:'High', dueAt:'2026-08-30T18:00'})
});
```

Dates use local ISO date-time strings such as `2026-08-30T18:00`. In the desktop app, enter dates as `YYYY-MM-DD HH:MM`, for example `2026-08-30 18:00`. Reminders appear as native Windows dialogs while Do It is running.
