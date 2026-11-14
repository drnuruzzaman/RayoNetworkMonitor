import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { cx } from './ui'

export function CopyText({ text }) {
  const [done, setDone] = useState(false)
  return (
    <button type="button" onClick={() => { navigator.clipboard?.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500) }}
      className="inline-flex items-center gap-1.5 rounded-md bg-slate-100 px-2 py-1 font-mono text-sm text-slate-800 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700">
      {text}{done ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5 opacity-60" />}
    </button>
  )
}

export function Steps({ items }) {
  return (
    <ol className="space-y-4">
      {items.map((it, i) => (
        <li key={i} className="flex gap-3">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-700 dark:bg-brand-950 dark:text-brand-300">{i + 1}</span>
          <div className="min-w-0 flex-1 text-sm text-slate-700 dark:text-slate-300">{it}</div>
        </li>
      ))}
    </ol>
  )
}

export function AdGuardInstallGuide() {
  return (
    <Steps items={[
      <>Open <b>PowerShell as Administrator</b> (right-click Start → <i>Terminal (Admin)</i>) and run the installer in the HomeNet folder:
        <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">powershell -ExecutionPolicy Bypass -File .\scripts\install-adguard.ps1</pre>
        <span className="help block">It downloads AdGuard Home from its official GitHub releases, installs it as a Windows service and opens the DNS port in Windows Firewall.</span></>,
      <>Open <CopyText text="http://127.0.0.1:3000" /> and follow AdGuard's welcome wizard. On the <b>Admin Web Interface</b> step pick <b>port 3000</b>. Leave <b>DNS server</b> on <b>All interfaces, port 53</b>.</>,
      <>Create an AdGuard username and password, then enter the same details below and press <b>Test connection</b>.</>,
    ]} />
  )
}

export function DnsGuide({ pcIp, gateway }) {
  const ip = pcIp || 'this PC\'s IP'
  return (
    <div className="space-y-6">
      <div>
        <h4 className="mb-3 text-sm font-semibold">Option A: every device at once (recommended)</h4>
        <Steps items={[
          <>On a computer, open your TPG modem's admin page at <CopyText text={`http://${gateway || '192.168.1.1'}`} /> and sign in. The password is usually on the sticker under the modem.</>,
          <>Find <b>LAN / DHCP settings</b> (sometimes under <i>Advanced → Network → LAN</i>). Add an <b>address reservation</b> so this PC always gets <CopyText text={ip} />.</>,
          <>In the same DHCP section, set the <b>Primary DNS server</b> to <CopyText text={ip} />. Leave the secondary DNS <b>blank</b>. A public DNS like 8.8.8.8 there would let devices skip monitoring.</>,
          <>If there's an <b>IPv6 DNS</b> option, turn IPv6 DNS off or point it at this PC too, so phones don't go around it.</>,
          <>Save, then turn Wi-Fi off and on (or restart) on each phone and tablet so they pick up the change.</>,
        ]} />
        <p className="help mt-3">Some ISP modems (including TPG's) hide the DNS setting. If yours does, but lets you switch its DHCP server off, use HomeNet's <a className="link" href="/dhcp">Address server</a> instead. Otherwise use Option B.</p>
      </div>
      <div className="border-t border-slate-200 pt-5 dark:border-slate-800">
        <h4 className="mb-3 text-sm font-semibold">Option B: set DNS on each device</h4>
        <div className="grid gap-3 text-sm sm:grid-cols-2">
          {[
            ['iPhone / iPad', `Settings → Wi-Fi → tap ⓘ next to your network → Configure DNS → Manual → remove existing servers → add ${ip}. While you're there, set Private Wi-Fi Address to Fixed (or Off).`],
            ['Android', `Settings → Network & internet → Wi-Fi → your network → ✎ / Advanced → IP settings: Static → DNS 1: ${ip}. Turn Private DNS off. Set Privacy to "Use device MAC".`],
            ['Windows', `Settings → Network & internet → Wi-Fi → Hardware properties → DNS server assignment → Edit → Manual → IPv4 preferred DNS: ${ip}.`],
            ['MacBook', `System Settings → Wi-Fi → Details… → DNS → remove existing entries → + ${ip}. Set Private Wi-Fi address to Fixed.`],
          ].map(([t, d]) => (
            <div key={t} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
              <p className="font-medium">{t}</p>
              <p className="mt-1 text-slate-600 dark:text-slate-400">{d}</p>
            </div>
          ))}
        </div>
      </div>
      <div className={cx('rounded-lg bg-slate-50 p-4 text-sm text-slate-600 dark:bg-slate-800/50 dark:text-slate-300')}>
        <p className="font-medium text-slate-800 dark:text-slate-200">Keep in mind</p>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>This PC must stay switched on, or devices pointed at it lose internet. Set Windows power settings to <b>never sleep</b>.</li>
          <li>Browsers with "Secure DNS / DNS over HTTPS" turned on and VPN apps can go around monitoring.</li>
          <li>Phones use a "private" MAC address per network. Set it to fixed so a device doesn't show up as new each time.</li>
        </ul>
      </div>
    </div>
  )
}
