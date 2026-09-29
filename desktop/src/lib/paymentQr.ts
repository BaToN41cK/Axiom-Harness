/** QR Model 2, version 10-L, byte mode (UTF-8 HTTPS URL, at most 271 bytes).
 * Fixed mask 0 is valid for every payload. No network, image assets or dependencies.
 */
export function paymentQr(url: string): boolean[][] {
  const bytes = new TextEncoder().encode(url);
  if (bytes.length > 271 || !url.startsWith("https://")) throw new Error("Некорректная ссылка для QR");
  const bits: number[] = [];
  const put = (value: number, count: number) => {
    for (let i = count - 1; i >= 0; i--) bits.push((value >>> i) & 1);
  };
  put(4, 4); put(bytes.length, 16);
  for (const byte of bytes) put(byte, 8);
  put(0, Math.min(4, 2192 - bits.length));
  while (bits.length % 8) bits.push(0);
  const data: number[] = [];
  for (let i = 0; i < bits.length; i += 8) data.push(bits.slice(i, i + 8).reduce((a, b) => a * 2 + b, 0));
  for (let i = 0; data.length < 274; i++) data.push(i % 2 ? 0x11 : 0xec);
  const mul = (a: number, b: number) => {
    let value = 0;
    for (let i = 7; i >= 0; i--) {
      value = (value << 1) ^ ((value >>> 7) * 0x11d);
      value ^= ((b >>> i) & 1) * a;
    }
    return value;
  };
  let divisor = [1];
  let root = 1;
  for (let i = 0; i < 18; i++) {
    const next = Array<number>(divisor.length + 1).fill(0);
    for (let j = 0; j < divisor.length; j++) {
      next[j] ^= divisor[j];
      next[j + 1] ^= mul(divisor[j], root);
    }
    divisor = next;
    root = mul(root, 2);
  }
  const blocks: number[][] = [], ecc: number[][] = [];
  let offset = 0;
  for (const length of [68, 68, 69, 69]) {
    const block = data.slice(offset, offset += length), remainder = Array<number>(18).fill(0);
    for (const byte of block) {
      const factor = byte ^ remainder.shift()!; remainder.push(0);
      for (let i = 0; i < 18; i++) remainder[i] ^= mul(divisor[i], factor);
    }
    blocks.push(block); ecc.push(remainder);
  }
  const code: number[] = [];
  for (let i = 0; i < 69; i++) for (const block of blocks) if (i < block.length) code.push(block[i]);
  for (let i = 0; i < 18; i++) for (const block of ecc) code.push(block[i]);
  const size = 57;
  const matrix = Array.from({ length: size }, () => Array<boolean>(size).fill(false));
  const reserved = matrix.map((row) => row.slice());
  const set = (x: number, y: number, value: boolean) => {
    if (x >= 0 && y >= 0 && x < size && y < size) { matrix[y][x] = value; reserved[y][x] = true; }
  };
  for (let i = 0; i < size; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }
  for (const [cx, cy] of [[3, 3], [53, 3], [3, 53]]) {
    for (let y = -4; y <= 4; y++) for (let x = -4; x <= 4; x++) {
      const d = Math.max(Math.abs(x), Math.abs(y)); set(cx + x, cy + y, d !== 2 && d !== 4);
    }
  }
  for (const y of [6, 28, 50]) for (const x of [6, 28, 50]) {
    if ((x === 6 && y === 6) || (x === 6 && y === 50) || (x === 50 && y === 6)) continue;
    for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++)
      set(x + dx, y + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
  }
  // Format: L (01), mask 000; BCH(15,5) and fixed XOR mask.
  let rem = 8 << 10;
  while (rem >= 1 << 10) rem ^= 0x537 << (Math.floor(Math.log2(rem)) - 10);
  const format = (8 << 10 | rem) ^ 0x5412;
  const bit = (v: number, i: number) => ((v >>> i) & 1) !== 0;
  for (let i = 0; i <= 5; i++) set(8, i, bit(format, i));
  set(8, 7, bit(format, 6)); set(8, 8, bit(format, 7)); set(7, 8, bit(format, 8));
  for (let i = 9; i < 15; i++) set(14 - i, 8, bit(format, i));
  for (let i = 0; i < 8; i++) set(size - 1 - i, 8, bit(format, i));
  for (let i = 8; i < 15; i++) set(8, size - 15 + i, bit(format, i));
  set(8, size - 8, true);
  rem = 10 << 12;
  while (rem >= 1 << 12) rem ^= 0x1f25 << (Math.floor(Math.log2(rem)) - 12);
  const version = (10 << 12) | rem;
  for (let i = 0; i < 18; i++) {
    const a = size - 11 + i % 3, b = Math.floor(i / 3);
    set(a, b, bit(version, i)); set(b, a, bit(version, i));
  }
  let index = 0;
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let vertical = 0; vertical < size; vertical++) for (let j = 0; j < 2; j++) {
      const x = right - j, y = ((right + 1) & 2) === 0 ? size - 1 - vertical : vertical;
      if (reserved[y][x]) continue;
      matrix[y][x] = bit(code[index >>> 3] ?? 0, 7 - (index & 7)) !== ((x + y) % 2 === 0);
      index++;
    }
  }
  return matrix;
}