import { useState } from 'react'

const API = import.meta.env.VITE_API_BASE_URL || ''

export default function App(){
  const [matches,setMatches]=useState([])
  const [status,setStatus]=useState({})

  async function loadUniverse(){
    await fetch(`${API}/load-universe`)
    alert('Universe Loaded')
  }

  async function runScan(){
    const res = await fetch(`${API}/scan?start=0&limit=50`)
    const data = await res.json()
    console.log(data)
    alert('Scan ran - check matches')
  }

  async function loadMatches(){
    const res = await fetch(`${API}/matches`)
    const data = await res.json()
    setMatches(data)
  }

  async function loadStatus(){
    const res = await fetch(`${API}/scan/status`)
    const data = await res.json()
    setStatus(data)
  }

  return (
    <div style={{padding:20}}>
      <h1>Momentum Screener</h1>

      <button onClick={loadUniverse}>Load Universe</button>
      <button onClick={runScan}>Run Scan</button>
      <button onClick={loadMatches}>Show Matches</button>
      <button onClick={loadStatus}>Status</button>

      <pre>{JSON.stringify(status,null,2)}</pre>

      <table border="1" cellPadding="5">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Price</th>
            <th>Change %</th>
            <th>Rel Vol</th>
            <th>Headline</th>
          </tr>
        </thead>
        <tbody>
          {matches.map(m=>(
            <tr key={m.symbol}>
              <td>{m.symbol}</td>
              <td>{m.price}</td>
              <td>{m.change}</td>
              <td>{m.relative_volume}</td>
              <td>{m.headline}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
