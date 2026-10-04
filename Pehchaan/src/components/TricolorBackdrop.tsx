import React, { useEffect, useRef } from 'react';

// Slow saffron, white and green ribbons on a pearl ground, drawn by a small
// WebGL shader. Rendered at reduced resolution and about 30 frames a second;
// one still frame when the viewer prefers reduced motion; paused while the tab
// is hidden. Without WebGL the CSS gradient underneath is all that shows.

const VERTEX = `attribute vec2 a_position;
void main() { gl_Position = vec4(a_position, 0.0, 1.0); }`;

const FRAGMENT = `precision mediump float;
uniform float u_time;
uniform vec2 u_resolution;

vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec2 mod289(vec2 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec3 permute(vec3 x) { return mod289(((x * 34.0) + 1.0) * x); }

float snoise(vec2 v) {
  const vec4 C = vec4(0.211324865405187, 0.366025403784439, -0.577350269189626, 0.024390243902439);
  vec2 i = floor(v + dot(v, C.yy));
  vec2 x0 = v - i + dot(i, C.xx);
  vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
  vec4 x12 = x0.xyxy + C.xxzz;
  x12.xy -= i1;
  i = mod289(i);
  vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0)) + i.x + vec3(0.0, i1.x, 1.0));
  vec3 m = max(0.5 - vec3(dot(x0, x0), dot(x12.xy, x12.xy), dot(x12.zw, x12.zw)), 0.0);
  m = m * m; m = m * m;
  vec3 x = 2.0 * fract(p * C.www) - 1.0;
  vec3 h = abs(x) - 0.5;
  vec3 ox = floor(x + 0.5);
  vec3 a0 = x - ox;
  m *= 1.79284291400159 - 0.85373472095314 * (a0 * a0 + h * h);
  vec3 g;
  g.x = a0.x * x0.x + h.x * x0.y;
  g.yz = a0.yz * x12.xz + h.yz * x12.yw;
  return 130.0 * dot(m, g);
}

void main() {
  vec2 uv = gl_FragCoord.xy / u_resolution.xy;
  vec2 p = (gl_FragCoord.xy * 2.0 - u_resolution.xy) / min(u_resolution.x, u_resolution.y);
  float t = u_time * 0.35;

  vec3 saffron = vec3(1.0, 0.45, 0.08);
  vec3 saffronLight = vec3(1.0, 0.72, 0.42);
  vec3 white = vec3(0.98, 0.99, 1.0);
  vec3 green = vec3(0.07, 0.65, 0.32);
  vec3 greenLight = vec3(0.35, 0.85, 0.55);
  vec3 navy = vec3(0.05, 0.22, 0.65);
  vec3 ground = vec3(0.95, 0.96, 0.98);

  float w1 = sin(p.x * 1.8 + t * 1.2 + snoise(p * 1.2 + vec2(t * 0.3, 0.0)) * 2.0);
  float w2 = cos(p.x * 2.2 - t * 0.9 + snoise(p * 1.6 - vec2(0.0, t * 0.4)) * 1.8);
  float w3 = sin(p.y * 2.0 + p.x * 1.5 + t * 1.5);

  float rS = smoothstep(0.45, 0.0, abs(p.y - (0.42 + 0.25 * sin(p.x * 1.5 + t) + 0.15 * w1)));
  float rW = smoothstep(0.40, 0.0, abs(p.y - (0.02 + 0.28 * sin(p.x * 1.7 + t * 1.1 + 1.0) + 0.12 * w2)));
  float rG = smoothstep(0.48, 0.0, abs(p.y - (-0.45 + 0.26 * sin(p.x * 1.4 + t * 0.95 + 2.1) + 0.14 * w3)));
  float sheen = pow(clamp(0.5 + 0.5 * sin((p.x + p.y * 0.8) * 3.5 - t * 2.2), 0.0, 1.0), 4.0) * 0.35;
  float rN = smoothstep(0.12, 0.0, abs(p.y - (0.02 + 0.28 * sin(p.x * 1.7 + t * 1.1 + 1.0)))) * 0.45;

  vec3 col = mix(ground, vec3(0.99, 0.99, 1.0), uv.y * 0.8 + 0.1);
  col = mix(col, vec3(0.92, 0.95, 0.99), clamp(snoise(vec2(p.x * 0.8 + t * 0.15, p.y * 0.8 - t * 0.1)) * 0.35 + 0.2, 0.0, 0.5));
  col = mix(col, saffron, rS * 0.82);
  col = mix(col, saffronLight, rS * sheen * 0.9);
  col = mix(col, green, rG * 0.78);
  col = mix(col, greenLight, rG * sheen * 0.85);
  col = mix(col, white, rW * 0.92);
  col = mix(col, navy, rN * 0.65);

  float edge = smoothstep(0.0, 1.4, length(p * vec2(0.85, 1.0)));
  col = mix(col, col * 0.96 + vec3(0.01, 0.02, 0.04), edge * 0.12);
  gl_FragColor = vec4(col, 1.0);
}`;

const RESOLUTION_SCALE = 0.5;
const FRAME_MS = 1000 / 30;

export const TricolorBackdrop: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const gl = canvas?.getContext('webgl', { antialias: false, alpha: false, powerPreference: 'low-power' });
    if (!canvas || !gl) return;

    const compile = (type: number, src: string) => {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      return s;
    };
    const prog = gl.createProgram()!;
    gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERTEX));
    gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAGMENT));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return;
    gl.useProgram(prog);
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const pos = gl.getAttribLocation(prog, 'a_position');
    gl.enableVertexAttribArray(pos);
    gl.vertexAttribPointer(pos, 2, gl.FLOAT, false, 0, 0);
    const uTime = gl.getUniformLocation(prog, 'u_time');
    const uRes = gl.getUniformLocation(prog, 'u_resolution');

    const resize = () => {
      const w = Math.max(1, Math.round(canvas.clientWidth * RESOLUTION_SCALE));
      const h = Math.max(1, Math.round(canvas.clientHeight * RESOLUTION_SCALE));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
      gl.viewport(0, 0, w, h);
      gl.uniform2f(uRes, w, h);
    };
    const draw = (ms: number) => {
      gl.uniform1f(uTime, ms / 1000);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    };

    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let frame = 0;
    let last = 0;
    const loop = (ms: number) => {
      frame = requestAnimationFrame(loop);
      if (document.hidden || ms - last < FRAME_MS) return;
      last = ms;
      draw(ms);
    };
    const observer = new ResizeObserver(() => {
      resize();
      if (still) draw(12000);
    });
    observer.observe(canvas);
    resize();
    if (still) draw(12000);
    else frame = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      // Free what this effect made, but keep the context: a canvas has only one,
      // and a lost one cannot be used again if the effect runs a second time.
      gl.deleteBuffer(buffer);
      gl.deleteProgram(prog);
    };
  }, []);

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden bg-[linear-gradient(160deg,#fff4ea_0%,#f4f5f9_45%,#eaf6ee_100%)]" aria-hidden="true">
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" />
      <div className="absolute -top-32 -left-32 w-96 h-96 rounded-full bg-gradient-to-br from-[#FF671F]/15 via-transparent to-transparent blur-3xl" />
      <div className="absolute -bottom-36 -right-32 w-96 h-96 rounded-full bg-gradient-to-tl from-[#046A38]/15 via-transparent to-transparent blur-3xl" />
    </div>
  );
};
