import { useCallback, useEffect, useState, useRef } from 'react'
import { fetchTransactions, fetchUser, initiateTransaction, resetMock } from './api'
import PhoneFrame from './components/PhoneFrame'
import HomeScreen from './components/HomeScreen'
import VerifyingScreen from './components/VerifyingScreen'
import ResultScreen from './components/ResultScreen'
import DemoControls, { DEMO_BUTTONS } from './components/DemoControls'
import CinematicText from './components/CinematicText'
import { useVerification } from './hooks/useVerification'
import type { AudioSource } from './hooks/useAudioCapture'
import type {
  DemoButton,
  GeminiSummary,
  HumeScores,
  QuestionTurn,
  Tier,
  Transaction,
  User,
  VerificationQuestion,
  VerifyResult,
} from './types'

type Screen = 'home' | 'verifying' | 'result'

// Utility for delays
const delay = (ms: number) => new Promise(r => setTimeout(r, ms))

export default function App() {
  const [screen, setScreen] = useState<Screen>('home')
  const [user, setUser] = useState<User | null>(null)
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [isLoading, setIsLoading] = useState(false)

  const [verifyingTier, setVerifyingTier] = useState<Tier>('MID_RISK')
  const [verifyingMerchant, setVerifyingMerchant] = useState('')
  const [humeScores, setHumeScores] = useState<HumeScores | null>(null)
  const [geminiSummary, setGeminiSummary] = useState<GeminiSummary | null>(null)
  const [countdown, setCountdown] = useState(5)
  const [videoStream, setVideoStream] = useState<MediaStream | null>(null)
  const [audioSource, setAudioSource] = useState<AudioSource>('silent')
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null)
  const [turns, setTurns] = useState<QuestionTurn[]>([])
  const [currentQuestion, setCurrentQuestion] = useState<VerificationQuestion | null>(null)

  const [isAutopilot, setIsAutopilot] = useState(false)
  const [cinematicStep, setCinematicStep] = useState(0)
  
  const verify = useVerification()
  const autopilotRunning = useRef(false)

  const loadData = useCallback(async () => {
    try {
      const [u, txs] = await Promise.all([fetchUser(), fetchTransactions()])
      setUser(u)
      setTransactions(txs)
    } catch (e) {
      console.error('Failed to load data:', e)
    }
  }, [])

  useEffect(() => {
    loadData()
    // Check URL for autopilot
    const params = new URLSearchParams(window.location.search)
    if (params.get('autopilot') === 'true') {
      setIsAutopilot(true)
    }
  }, [loadData])

  const handleDemoButton = useCallback(
    async (button: DemoButton) => {
      setIsLoading(true)
      let res: Awaited<ReturnType<typeof initiateTransaction>>
      try {
        res = await initiateTransaction(button.merchant, button.amount, button.scenario)
      } catch (e) {
        setIsLoading(false)
        alert(`Error: ${String(e)}`)
        return
      }
      setIsLoading(false)

      // NO_RISK: auto-approved — show result immediately, refresh list in background
      if (res.tier === 'NO_RISK') {
        setVerifyResult({
          verdict: 'APPROVED',
          rationale: 'Low-risk transaction — approved automatically.',
        })
        setScreen('result')
        void loadData()
        return
      }

      // MID / HIGH: set up verification state
      setVerifyingTier(res.tier)
      setVerifyingMerchant(button.merchant)
      setCountdown(5)
      setHumeScores(null)
      setGeminiSummary(null)
      setVerifyResult(null)
      setVideoStream(null)
      setAudioSource('silent')
      setTurns([])
      setCurrentQuestion(null)

      // Refresh transaction list so the PENDING_VERIFICATION row appears
      await loadData()

      setScreen('verifying')

      return new Promise<void>((resolve) => {
        verify.run({
          initiateRes: res,
          onHumeUpdate: setHumeScores,
          onGeminiUpdate: setGeminiSummary,
          onCountdown: setCountdown,
          onVideoStream: setVideoStream,
          onAudioSource: setAudioSource,
          onTurnsUpdate: setTurns,
          onCurrentQuestion: setCurrentQuestion,
          onComplete: (result) => {
            setVerifyResult(result)
            // Refresh to show final status (HELD_FOR_REVIEW / FROZEN / APPROVED)
            void loadData()
            setScreen('result')
            resolve()
          },
          onError: (msg) => {
            setVerifyResult({
              verdict: 'HELD_FOR_REVIEW',
              rationale: `Verification error: ${msg}`,
            })
            void loadData()
            setScreen('result')
            resolve()
          },
        })
      })
    },
    [verify, loadData],
  )

  const handleBack = useCallback(async () => {
    verify.cleanup()
    setVideoStream(null)
    setScreen('home')
    await loadData()
  }, [verify, loadData])

  // Autopilot Engine
  useEffect(() => {
    if (!isAutopilot || autopilotRunning.current) return
    autopilotRunning.current = true

    const runAutopilot = async () => {
      try {
        await resetMock() // ensure clean state
      } catch {}
      await loadData()
      
      setCinematicStep(0) // "Welcome"
      await delay(4000)

      // SCENARIO 1: SUSPICIOUS
      setCinematicStep(1) // "Real-time Verification"
      await handleDemoButton(DEMO_BUTTONS[1]) // FastWire (Suspicious)
      
      // Wait during verification (5s + a bit)
      await delay(6000)
      
      setCinematicStep(2) // "Interception"
      // Wait on result screen
      await delay(5000)
      await handleBack()
      
      // Home screen, wait to let viewer see updated list
      setCinematicStep(3) // "Seamless Integration"
      await delay(3000)
      
      // SCENARIO 2: FRAUDULENT
      setCinematicStep(4) // "High-Risk Threats"
      await handleDemoButton(DEMO_BUTTONS[2]) // Unknown LLP (Fraudulent)
      
      await delay(6000) // Verification
      
      setCinematicStep(5) // "Absolute Security"
      await delay(5000)
      await handleBack()
      
      setCinematicStep(6) // "The Future of Banking"
    }

    runAutopilot()
  }, [isAutopilot, handleDemoButton, handleBack, loadData])


  return (
    <div className="flex items-center justify-center min-h-screen bg-black overflow-hidden relative">
      {/* Subtle cinematic background glow if autopilot */}
      {isAutopilot && (
         <div className="absolute inset-0 pointer-events-none">
           <div className="absolute top-0 left-1/4 w-[800px] h-[800px] bg-blue-900/10 rounded-full blur-[120px]" />
           <div className="absolute bottom-0 right-1/4 w-[800px] h-[800px] bg-purple-900/10 rounded-full blur-[120px]" />
         </div>
      )}

      <div className={`flex items-center gap-16 relative z-10 ${isAutopilot ? 'w-full max-w-[1200px] justify-between px-16' : ''}`}>
        
        {isAutopilot && (
          <div className="flex-1 flex flex-col justify-center max-w-[500px]">
             <CinematicText step={cinematicStep} />
          </div>
        )}

        <PhoneFrame>
          <div key={screen} className="screen-enter w-full h-full relative">
            {screen === 'home' && (
              <HomeScreen user={user} transactions={transactions} />
            )}
            {screen === 'verifying' && (
              <VerifyingScreen
                tier={verifyingTier}
                humeScores={humeScores}
                geminiSummary={geminiSummary}
                countdown={countdown}
                videoStream={videoStream}
                audioSource={audioSource}
                merchant={verifyingMerchant}
                turns={turns}
                currentQuestion={currentQuestion}
              />
            )}
            {screen === 'result' && verifyResult && (
              <ResultScreen result={verifyResult} onBack={isAutopilot ? () => {} : handleBack} />
            )}
            
            {/* Fake cursor for autopilot - optional, can just click via logic */}
          </div>
        </PhoneFrame>

        {!isAutopilot && (
          <DemoControls onDemoPress={handleDemoButton} isLoading={isLoading} />
        )}
      </div>
    </div>
  )
}
