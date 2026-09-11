import streamlit as st
import streamlit.components.v1 as components


st.set_page_config(
    page_title="Snake | FPL Advisor",
    page_icon="🐍",
    layout="centered",
)

st.markdown(
    """
    <style>
    [data-testid="stAppViewContainer"] {
        background:
            radial-gradient(circle at 15% 10%, rgba(45, 212, 191, 0.12), transparent 30%),
            radial-gradient(circle at 85% 15%, rgba(129, 140, 248, 0.14), transparent 35%),
            #07111f;
    }
    [data-testid="stHeader"] { background: transparent; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🐍 Snake")
st.caption("A quick break between transfers. Collect the stars, beat your high score.")

components.html(
    """
    <style>
      :root {
        color-scheme: dark;
        --ink: #e5eef8;
        --muted: #8ea4bb;
        --panel: rgba(12, 29, 48, .84);
        --line: rgba(148, 163, 184, .19);
        --teal: #2dd4bf;
        --lime: #bef264;
        --violet: #a78bfa;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        color: var(--ink);
        background: transparent;
      }
      .game-shell {
        width: min(100%, 600px);
        margin: 0 auto;
        padding: 8px 0 18px;
      }
      .game-card {
        padding: clamp(16px, 4vw, 28px);
        border: 1px solid var(--line);
        border-radius: 28px;
        background: linear-gradient(145deg, rgba(15, 39, 62, .94), rgba(6, 20, 36, .96));
        box-shadow: 0 24px 65px rgba(0, 0, 0, .3), inset 0 1px 0 rgba(255,255,255,.05);
      }
      .game-heading {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 18px;
      }
      .game-heading h2 { margin: 0; font-size: clamp(1.35rem, 4vw, 1.75rem); letter-spacing: -.03em; }
      .game-heading p { margin: 5px 0 0; color: var(--muted); font-size: .88rem; }
      .badge {
        padding: 7px 10px;
        border: 1px solid rgba(167, 139, 250, .3);
        border-radius: 999px;
        background: rgba(167, 139, 250, .1);
        color: #c4b5fd;
        font-size: .72rem;
        font-weight: 700;
        letter-spacing: .08em;
        text-transform: uppercase;
        white-space: nowrap;
      }
      .score-row { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-bottom: 16px; }
      .score-box {
        padding: 11px 14px;
        border: 1px solid var(--line);
        border-radius: 15px;
        background: rgba(255,255,255,.035);
      }
      .score-box span { display: block; color: var(--muted); font-size: .7rem; font-weight: 700; letter-spacing: .11em; text-transform: uppercase; }
      .score-box strong { display: block; margin-top: 3px; color: var(--ink); font-size: 1.35rem; line-height: 1; }
      .board-wrap {
        position: relative;
        width: min(100%, 420px);
        margin: 0 auto;
        aspect-ratio: 1;
        overflow: hidden;
        border: 1px solid rgba(45, 212, 191, .28);
        border-radius: 20px;
        background: #091b2a;
        box-shadow: 0 0 0 5px rgba(45, 212, 191, .04), 0 15px 35px rgba(0,0,0,.3);
      }
      canvas { display: block; width: 100%; height: 100%; touch-action: none; }
      .status {
        position: absolute;
        inset: 0;
        display: grid;
        place-items: center;
        padding: 28px;
        text-align: center;
        pointer-events: none;
        background: linear-gradient(180deg, rgba(4, 14, 26, .1), rgba(4, 14, 26, .58));
      }
      .status[hidden] { display: none; }
      .status-inner { max-width: 260px; padding: 18px; border: 1px solid rgba(255,255,255,.13); border-radius: 18px; background: rgba(5, 17, 30, .82); backdrop-filter: blur(10px); }
      .status h3 { margin: 0 0 6px; font-size: 1.3rem; }
      .status p { margin: 0; color: var(--muted); font-size: .84rem; line-height: 1.4; }
      .actions { display: flex; gap: 10px; margin: 16px 0 12px; }
      button {
        flex: 1;
        min-height: 45px;
        border: 1px solid rgba(45, 212, 191, .38);
        border-radius: 13px;
        background: linear-gradient(135deg, #2dd4bf, #14b8a6);
        color: #042f2e;
        cursor: pointer;
        font: inherit;
        font-size: .87rem;
        font-weight: 800;
        transition: transform .16s ease, filter .16s ease;
      }
      button.secondary { border-color: var(--line); background: rgba(255,255,255,.05); color: var(--ink); }
      button:hover { filter: brightness(1.08); transform: translateY(-1px); }
      button:active { transform: translateY(1px); }
      .hint { margin: 0; color: var(--muted); text-align: center; font-size: .75rem; }
      .d-pad { display: grid; grid-template-columns: repeat(3, 52px); grid-template-rows: repeat(2, 45px); justify-content: center; gap: 7px; margin: 17px auto 0; }
      .d-pad button { min-height: 0; border-color: var(--line); background: rgba(255,255,255,.07); color: var(--ink); font-size: 1.15rem; }
      .d-pad button:first-child { grid-column: 2; }
      .d-pad button:nth-child(2) { grid-column: 1; grid-row: 2; }
      .d-pad button:nth-child(3) { grid-column: 2; grid-row: 2; }
      .d-pad button:nth-child(4) { grid-column: 3; grid-row: 2; }
      @media (max-width: 420px) {
        .game-card { border-radius: 22px; }
        .d-pad { grid-template-columns: repeat(3, 48px); }
      }
    </style>

    <main class="game-shell">
      <section class="game-card" aria-label="Snake game">
        <header class="game-heading">
          <div>
            <h2>Neon Garden</h2>
            <p>Guide your snake to the next star.</p>
          </div>
          <span class="badge" id="statusBadge">Ready</span>
        </header>
        <div class="score-row" aria-live="polite">
          <div class="score-box"><span>Score</span><strong id="score">0</strong></div>
          <div class="score-box"><span>High score</span><strong id="highScore">0</strong></div>
        </div>
        <div class="board-wrap">
          <canvas id="board" width="420" height="420" tabindex="0" aria-label="Snake game board"></canvas>
          <div class="status" id="overlay">
            <div class="status-inner">
              <h3 id="overlayTitle">Ready to play?</h3>
              <p id="overlayText">Use arrow keys or WASD to move. On mobile, use the controls below.</p>
            </div>
          </div>
        </div>
        <div class="actions">
          <button id="startButton">Start game</button>
          <button class="secondary" id="restartButton">Restart</button>
        </div>
        <p class="hint">Arrow keys / WASD to move · Space to pause</p>
        <div class="d-pad" aria-label="Touch controls">
          <button data-direction="up" aria-label="Move up">↑</button>
          <button data-direction="left" aria-label="Move left">←</button>
          <button data-direction="down" aria-label="Move down">↓</button>
          <button data-direction="right" aria-label="Move right">→</button>
        </div>
      </section>
    </main>

    <script>
      (() => {
        const canvas = document.getElementById("board");
        const ctx = canvas.getContext("2d");
        const grid = 21;
        const tile = canvas.width / grid;
        const scoreEl = document.getElementById("score");
        const highScoreEl = document.getElementById("highScore");
        const badge = document.getElementById("statusBadge");
        const overlay = document.getElementById("overlay");
        const overlayTitle = document.getElementById("overlayTitle");
        const overlayText = document.getElementById("overlayText");
        const startButton = document.getElementById("startButton");
        const restartButton = document.getElementById("restartButton");
        const highScoreKey = "neon-snake-high-score";
        let highScore = Number(localStorage.getItem(highScoreKey)) || 0;
        let snake;
        let food;
        let direction;
        let nextDirection;
        let score;
        let running = false;
        let paused = false;
        let timer;
        let pulse = 0;

        highScoreEl.textContent = highScore;

        function randomFood() {
          let candidate;
          do {
            candidate = { x: Math.floor(Math.random() * grid), y: Math.floor(Math.random() * grid) };
          } while (snake.some((part) => part.x === candidate.x && part.y === candidate.y));
          return candidate;
        }

        function reset() {
          snake = [{ x: 10, y: 11 }, { x: 9, y: 11 }, { x: 8, y: 11 }];
          food = randomFood();
          direction = { x: 1, y: 0 };
          nextDirection = { x: 1, y: 0 };
          score = 0;
          scoreEl.textContent = score;
          draw();
        }

        function showOverlay(title, text) {
          overlayTitle.textContent = title;
          overlayText.textContent = text;
          overlay.hidden = false;
        }

        function setState(label, color) {
          badge.textContent = label;
          badge.style.color = color;
        }

        function start() {
          if (running && !paused) return;
          if (!running) reset();
          running = true;
          paused = false;
          overlay.hidden = true;
          setState("Playing", "#bef264");
          startButton.textContent = "Pause";
          canvas.focus();
          clearInterval(timer);
          timer = setInterval(step, Math.max(72, 145 - score * 2));
        }

        function pause() {
          if (!running) return;
          paused = !paused;
          if (paused) {
            clearInterval(timer);
            showOverlay("Paused", "Press Space or Resume to keep going.");
            setState("Paused", "#fbbf24");
            startButton.textContent = "Resume";
          } else {
            overlay.hidden = true;
            setState("Playing", "#bef264");
            startButton.textContent = "Pause";
            timer = setInterval(step, Math.max(72, 145 - score * 2));
          }
        }

        function gameOver() {
          running = false;
          paused = false;
          clearInterval(timer);
          if (score > highScore) {
            highScore = score;
            localStorage.setItem(highScoreKey, highScore);
            highScoreEl.textContent = highScore;
            showOverlay("New high score!", `You scored ${score}. Ready for another run?`);
          } else {
            showOverlay("Game over", `You scored ${score}. Press Restart to try again.`);
          }
          setState("Game over", "#fb7185");
          startButton.textContent = "Start game";
          draw();
        }

        function step() {
          direction = nextDirection;
          const head = { x: snake[0].x + direction.x, y: snake[0].y + direction.y };
          if (
            head.x < 0 || head.x >= grid || head.y < 0 || head.y >= grid ||
            snake.some((part) => part.x === head.x && part.y === head.y)
          ) {
            gameOver();
            return;
          }
          snake.unshift(head);
          if (head.x === food.x && head.y === food.y) {
            score += 10;
            scoreEl.textContent = score;
            food = randomFood();
            clearInterval(timer);
            timer = setInterval(step, Math.max(72, 145 - score * 2));
          } else {
            snake.pop();
          }
          pulse += 1;
          draw();
        }

        function setDirection(next) {
          if (next.x + direction.x === 0 && next.y + direction.y === 0) return;
          nextDirection = next;
          if (!running) start();
        }

        function draw() {
          ctx.fillStyle = "#091b2a";
          ctx.fillRect(0, 0, canvas.width, canvas.height);
          ctx.strokeStyle = "rgba(148, 163, 184, .075)";
          ctx.lineWidth = 1;
          for (let i = 1; i < grid; i += 1) {
            ctx.beginPath(); ctx.moveTo(i * tile, 0); ctx.lineTo(i * tile, canvas.height); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(0, i * tile); ctx.lineTo(canvas.width, i * tile); ctx.stroke();
          }
          const glow = 4 + Math.sin(pulse / 5) * 2;
          ctx.shadowBlur = 16 + glow;
          ctx.shadowColor = "#fbbf24";
          ctx.fillStyle = "#fbbf24";
          ctx.beginPath();
          ctx.arc((food.x + .5) * tile, (food.y + .5) * tile, tile * .3, 0, Math.PI * 2);
          ctx.fill();
          ctx.shadowBlur = 0;
          snake.forEach((part, index) => {
            const inset = index === 0 ? 1.5 : 2.5;
            ctx.fillStyle = index === 0 ? "#bef264" : `rgba(45, 212, 191, ${Math.max(.48, 1 - index / (snake.length * 1.4))})`;
            ctx.shadowColor = "#2dd4bf";
            ctx.shadowBlur = index === 0 ? 12 : 5;
            ctx.beginPath();
            ctx.roundRect(part.x * tile + inset, part.y * tile + inset, tile - inset * 2, tile - inset * 2, 5);
            ctx.fill();
          });
          ctx.shadowBlur = 0;
        }

        startButton.addEventListener("click", () => (running && !paused ? pause() : start()));
        restartButton.addEventListener("click", () => {
          clearInterval(timer);
          running = false;
          paused = false;
          reset();
          showOverlay("Ready to play?", "Use arrow keys or WASD to move. On mobile, use the controls below.");
          setState("Ready", "#c4b5fd");
          startButton.textContent = "Start game";
          canvas.focus();
        });
        document.addEventListener("keydown", (event) => {
          const key = event.key.toLowerCase();
          const moves = {
            arrowup: { x: 0, y: -1 }, w: { x: 0, y: -1 },
            arrowdown: { x: 0, y: 1 }, s: { x: 0, y: 1 },
            arrowleft: { x: -1, y: 0 }, a: { x: -1, y: 0 },
            arrowright: { x: 1, y: 0 }, d: { x: 1, y: 0 },
          };
          if (moves[key]) { event.preventDefault(); setDirection(moves[key]); }
          if (key === " " || key === "spacebar") { event.preventDefault(); pause(); }
        });
        document.querySelectorAll("[data-direction]").forEach((button) => {
          button.addEventListener("click", () => {
            const directions = {
              up: { x: 0, y: -1 }, down: { x: 0, y: 1 },
              left: { x: -1, y: 0 }, right: { x: 1, y: 0 },
            };
            setDirection(directions[button.dataset.direction]);
          });
        });
        reset();
      })();
    </script>
    """,
    height=790,
    scrolling=False,
)
