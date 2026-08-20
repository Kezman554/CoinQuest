import { useEffect, useState } from 'react'
import './App.css'

type Health = {
  status: string
  timezone: string
  local_time: string
}

function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/health')
      .then((response) => {
        if (!response.ok) throw new Error(`API returned ${response.status}`)
        return response.json() as Promise<Health>
      })
      .then(setHealth)
      .catch((err: Error) => setError(err.message))
  }, [])

  return (
    <main>
      <h1>CoinQuest</h1>
      {error && <p role="alert">Cannot reach the API: {error}</p>}
      {health && (
        <p>
          API {health.status} — {health.timezone} — {health.local_time}
        </p>
      )}
      {!health && !error && <p>Checking the API…</p>}
    </main>
  )
}

export default App
