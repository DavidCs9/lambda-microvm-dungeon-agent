import { useEffect, useRef } from "react";
import { Application, Container, Graphics, Text } from "pixi.js";
import { disposeAudio, playDiceSfx, unlockAudio } from "./audio";

export type Screen =
  | "landing"
  | "ritual"
  | "phase"
  | "opening"
  | "play"
  | "outcome";

export type DiceBeat = {
  roll: number;
  difficulty: number;
  success: boolean;
  turnId: string;
} | null;

type Props = {
  screen: Screen;
  diceBeat: DiceBeat;
};

const DEEP = 0x0c0a09;
const EMBER = 0xd9773a;
const FOG = 0x1c1714;
const INK = 0xf3ebe0;

type Mood = {
  emberRate: number;
  emberSpeed: number;
  fogAlpha: number;
  emberAlpha: number;
};

const MOOD: Record<Screen, Mood> = {
  landing: { emberRate: 0.55, emberSpeed: 0.35, fogAlpha: 0.35, emberAlpha: 0.45 },
  ritual: { emberRate: 0.75, emberSpeed: 0.45, fogAlpha: 0.4, emberAlpha: 0.55 },
  phase: { emberRate: 0.85, emberSpeed: 0.55, fogAlpha: 0.42, emberAlpha: 0.6 },
  opening: { emberRate: 0.35, emberSpeed: 0.22, fogAlpha: 0.28, emberAlpha: 0.3 },
  play: { emberRate: 1.1, emberSpeed: 0.7, fogAlpha: 0.48, emberAlpha: 0.75 },
  outcome: { emberRate: 0.4, emberSpeed: 0.25, fogAlpha: 0.5, emberAlpha: 0.35 },
};

type Dust = {
  g: Graphics;
  x: number;
  y: number;
  vx: number;
  vy: number;
  size: number;
  baseAlpha: number;
  phase: number;
};

type StageState = {
  fog: Graphics;
  vignette: Graphics;
  glow: Graphics;
  dust: Dust[];
  diceLayer: Container;
  mood: Mood;
  w: number;
  h: number;
  diceAnim: DiceAnim | null;
  lastTurnId: string | null;
};

type DiceAnim = {
  root: Container;
  body: Graphics;
  label: Text;
  t: number;
  duration: number;
  success: boolean;
  roll: number;
  done: boolean;
};

function regularPoly(
  g: Graphics,
  cx: number,
  cy: number,
  r: number,
  sides: number,
  rotation: number,
): void {
  const pts: number[] = [];
  for (let i = 0; i < sides; i++) {
    const a = rotation + (i / sides) * Math.PI * 2 - Math.PI / 2;
    pts.push(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
  }
  g.poly(pts);
}

function drawFog(g: Graphics, w: number, h: number, alpha: number): void {
  g.clear();
  // warm floor wash
  g.ellipse(w * 0.5, h * 1.05, w * 0.75, h * 0.45);
  g.fill({ color: EMBER, alpha: alpha * 0.18 });
  // drifting fog blobs
  g.ellipse(w * 0.22, h * 0.55, w * 0.35, h * 0.28);
  g.fill({ color: FOG, alpha: alpha * 0.55 });
  g.ellipse(w * 0.78, h * 0.42, w * 0.32, h * 0.3);
  g.fill({ color: FOG, alpha: alpha * 0.45 });
  g.ellipse(w * 0.5, h * 0.7, w * 0.5, h * 0.25);
  g.fill({ color: FOG, alpha: alpha * 0.35 });
}

function drawVignette(g: Graphics, w: number, h: number): void {
  g.clear();
  const bands = 8;
  for (let i = bands; i >= 1; i--) {
    const t = i / bands;
    const insetX = (w * 0.08) * (1 - t);
    const insetY = (h * 0.1) * (1 - t);
    g.rect(insetX, insetY, w - insetX * 2, h - insetY * 2);
    g.stroke({
      width: Math.max(w, h) * 0.12,
      color: DEEP,
      alpha: 0.08 + (1 - t) * 0.22,
      alignment: 1,
    });
  }
  // soft center ember glow hole stays via glow layer
}

function drawGlow(g: Graphics, w: number, h: number, alpha: number): void {
  g.clear();
  g.ellipse(w * 0.5, h * 0.62, w * 0.28, h * 0.18);
  g.fill({ color: EMBER, alpha: alpha * 0.12 });
  g.ellipse(w * 0.5, h * 0.58, w * 0.12, h * 0.08);
  g.fill({ color: EMBER, alpha: alpha * 0.18 });
}

function spawnDust(w: number, h: number, mood: Mood): Dust {
  const size = 0.8 + Math.random() * 2.2;
  const g = new Graphics();
  g.circle(0, 0, size);
  g.fill({ color: EMBER, alpha: 1 });
  const d: Dust = {
    g,
    x: Math.random() * w,
    y: Math.random() * h,
    vx: (Math.random() - 0.5) * mood.emberSpeed * 0.4,
    vy: -0.15 - Math.random() * mood.emberSpeed * 0.6,
    size,
    baseAlpha: (0.15 + Math.random() * 0.55) * mood.emberAlpha,
    phase: Math.random() * Math.PI * 2,
  };
  d.g.position.set(d.x, d.y);
  d.g.alpha = d.baseAlpha;
  return d;
}

function layoutAtmosphere(state: StageState): void {
  drawFog(state.fog, state.w, state.h, state.mood.fogAlpha);
  drawVignette(state.vignette, state.w, state.h);
  drawGlow(state.glow, state.w, state.h, state.mood.emberAlpha);
}

function startDiceBeat(state: StageState, beat: NonNullable<DiceBeat>): void {
  if (state.diceAnim) {
    state.diceAnim.root.destroy({ children: true });
    state.diceAnim = null;
  }

  const root = new Container();
  root.position.set(state.w * 0.5, state.h * 0.42);
  root.alpha = 0;

  const body = new Graphics();
  const label = new Text({
    text: String(beat.roll),
    style: {
      fontFamily: "Cinzel, Times New Roman, serif",
      fontSize: 56,
      fontWeight: "700",
      fill: INK,
      dropShadow: {
        color: DEEP,
        blur: 4,
        distance: 2,
        alpha: 0.8,
      },
    },
  });
  label.anchor.set(0.5);

  root.addChild(body);
  root.addChild(label);
  state.diceLayer.addChild(root);

  state.diceAnim = {
    root,
    body,
    label,
    t: 0,
    duration: 1.35,
    success: beat.success,
    roll: beat.roll,
    done: false,
  };
  state.lastTurnId = beat.turnId;

  void playDiceSfx(beat.success);
}

function drawDieFace(anim: DiceAnim, spin: number, scale: number): void {
  const { body, label, success } = anim;
  body.clear();
  const r = 72 * scale;
  // outer plate
  regularPoly(body, 0, 0, r, 6, spin);
  body.fill({ color: success ? 0x2a1810 : 0x141110, alpha: 0.92 });
  body.stroke({ width: 3, color: success ? EMBER : 0x6b5a4a, alpha: 0.95 });
  // inner facet rings (d20-ish)
  regularPoly(body, 0, 0, r * 0.72, 6, -spin * 0.6);
  body.stroke({ width: 1.5, color: EMBER, alpha: success ? 0.75 : 0.35 });
  regularPoly(body, 0, 0, r * 0.42, 3, spin * 1.2);
  body.stroke({ width: 1, color: INK, alpha: 0.25 });

  label.scale.set(scale);
  label.style.fill = success ? INK : 0xc4b5a0;
}

function tickDice(anim: DiceAnim, dt: number): void {
  anim.t += dt;
  const u = Math.min(1, anim.t / anim.duration);

  if (u < 0.55) {
    // tumble
    const p = u / 0.55;
    const spin = p * Math.PI * 8;
    const bounce = 1 + Math.sin(p * Math.PI * 6) * 0.12 * (1 - p);
    anim.root.alpha = Math.min(1, p * 3);
    anim.root.rotation = spin * 0.15;
    anim.root.scale.set(0.85 + bounce * 0.2);
    // scramble digits while tumbling
    anim.label.text = String(1 + Math.floor(Math.random() * 20));
    drawDieFace(anim, spin, bounce);
  } else {
    // settle on real result
    const p = (u - 0.55) / 0.45;
    const ease = 1 - Math.pow(1 - p, 3);
    anim.label.text = String(anim.roll);
    anim.root.alpha = 1;
    anim.root.rotation = (1 - ease) * 0.2;
    const punch = 1 + Math.sin(ease * Math.PI) * 0.18;
    anim.root.scale.set(punch);
    drawDieFace(anim, ease * 0.15, 1);
    if (anim.success) {
      anim.root.alpha = 0.85 + Math.sin(anim.t * 8) * 0.15;
    }
  }

  if (u >= 1 && !anim.done) {
    anim.done = true;
  }
  // fade out after settle
  if (anim.t > anim.duration + 1.8) {
    anim.root.alpha = Math.max(0, 1 - (anim.t - anim.duration - 1.8) / 0.7);
  }
}

/**
 * Full-viewport Pixi atmosphere behind the React UI.
 * Owns spectacle only — no networking or game rules.
 */
export function AtmosphereStage({ screen, diceBeat }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const appRef = useRef<Application | null>(null);
  const stateRef = useRef<StageState | null>(null);
  const screenRef = useRef(screen);
  const diceRef = useRef(diceBeat);
  screenRef.current = screen;
  diceRef.current = diceBeat;

  // Mount Pixi + audio unlock gesture
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    let cancelled = false;
    let ready = false;
    const app = new Application();
    appRef.current = app;

    const onGesture = () => {
      void unlockAudio();
      window.removeEventListener("pointerdown", onGesture);
      window.removeEventListener("keydown", onGesture);
    };
    window.addEventListener("pointerdown", onGesture, { once: true });
    window.addEventListener("keydown", onGesture, { once: true });

    const syncSize = () => {
      const w = Math.max(1, host.clientWidth);
      const h = Math.max(1, host.clientHeight);
      app.renderer.resize(w, h);
    };

    void (async () => {
      try {
        await app.init({
          width: Math.max(1, host.clientWidth),
          height: Math.max(1, host.clientHeight),
          background: DEEP,
          antialias: true,
          autoDensity: true,
          resolution: Math.min(window.devicePixelRatio || 1, 2),
          preference: "webgl",
        });
      } catch (error) {
        console.error("Pixi init failed", error);
        return;
      }
      ready = true;
      if (cancelled) {
        app.destroy(true);
        return;
      }

      host.appendChild(app.canvas);
      app.canvas.style.display = "block";
      app.canvas.style.width = "100%";
      app.canvas.style.height = "100%";
      syncSize();
      window.addEventListener("resize", syncSize);

      const fog = new Graphics();
      const glow = new Graphics();
      const vignette = new Graphics();
      const dustRoot = new Container();
      const diceLayer = new Container();

      app.stage.addChild(fog);
      app.stage.addChild(glow);
      app.stage.addChild(dustRoot);
      app.stage.addChild(vignette);
      app.stage.addChild(diceLayer);

      const mood = MOOD[screenRef.current];
      const state: StageState = {
        fog,
        vignette,
        glow,
        dust: [],
        diceLayer,
        mood,
        w: app.screen.width,
        h: app.screen.height,
        diceAnim: null,
        lastTurnId: null,
      };
      stateRef.current = state;

      const targetCount = Math.round(48 * mood.emberRate);
      for (let i = 0; i < targetCount; i++) {
        const d = spawnDust(state.w, state.h, mood);
        state.dust.push(d);
        dustRoot.addChild(d.g);
      }
      layoutAtmosphere(state);

      app.ticker.add((ticker) => {
        const s = stateRef.current;
        if (!s) return;
        const dt = ticker.deltaMS / 1000;
        const w = app.screen.width;
        const h = app.screen.height;

        if (w !== s.w || h !== s.h) {
          s.w = w;
          s.h = h;
          layoutAtmosphere(s);
          if (s.diceAnim) {
            s.diceAnim.root.position.set(w * 0.5, h * 0.42);
          }
        }

        // sync mood from screen
        const nextMood = MOOD[screenRef.current];
        if (nextMood !== s.mood) {
          s.mood = nextMood;
          layoutAtmosphere(s);
          const want = Math.round(48 * nextMood.emberRate);
          while (s.dust.length < want) {
            const d = spawnDust(s.w, s.h, nextMood);
            s.dust.push(d);
            dustRoot.addChild(d.g);
          }
          while (s.dust.length > want) {
            const d = s.dust.pop();
            d?.g.destroy();
          }
        }

        // dust drift
        for (const d of s.dust) {
          d.phase += dt;
          d.x += d.vx + Math.sin(d.phase) * 0.15;
          d.y += d.vy * (0.7 + s.mood.emberSpeed);
          if (d.y < -8) {
            d.y = s.h + 4;
            d.x = Math.random() * s.w;
          }
          if (d.x < -8) d.x = s.w + 4;
          if (d.x > s.w + 8) d.x = -4;
          d.g.position.set(d.x, d.y);
          d.g.alpha =
            d.baseAlpha *
            s.mood.emberAlpha *
            (0.55 + 0.45 * Math.sin(d.phase * 1.7));
        }

        // dice beat trigger
        const beat = diceRef.current;
        if (beat && beat.turnId !== s.lastTurnId) {
          startDiceBeat(s, beat);
        }

        if (s.diceAnim) {
          tickDice(s.diceAnim, dt);
          if (s.diceAnim.root.alpha <= 0 && s.diceAnim.t > s.diceAnim.duration + 2.4) {
            s.diceAnim.root.destroy({ children: true });
            s.diceAnim = null;
          }
        }
      });
    })();

    return () => {
      cancelled = true;
      window.removeEventListener("pointerdown", onGesture);
      window.removeEventListener("keydown", onGesture);
      window.removeEventListener("resize", syncSize);
      stateRef.current = null;
      if (ready && appRef.current) {
        try {
          appRef.current.destroy(true);
        } catch (error) {
          console.warn("Pixi destroy failed", error);
        }
        appRef.current = null;
      }
      disposeAudio();
    };
  }, []);

  // React to diceBeat immediately (ticker also polls; this catches same-frame mounts)
  useEffect(() => {
    const s = stateRef.current;
    if (!s || !diceBeat) return;
    if (diceBeat.turnId === s.lastTurnId) return;
    startDiceBeat(s, diceBeat);
  }, [diceBeat]);

  return (
    <div
      ref={hostRef}
      aria-hidden
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 0,
        pointerEvents: "none",
      }}
    />
  );
}
