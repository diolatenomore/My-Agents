import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import type { SkillInfo, SkillSegment } from '../../types';
import { joinSegments } from '../../types';

export interface ComposerValue {
  /** 纯文本（skill 占位符不贡献字符，拼接处空白归一化） */
  text: string;
  /** 按出现顺序去重的技能名 */
  skills: string[];
  /** 整条输入的有序分段（chip 位置 = 数组顺序） */
  segments: SkillSegment[];
}

export interface SkillComposerHandle {
  clear: () => void;
  focus: () => void;
}

interface SkillComposerProps {
  placeholder: string;
  /** 可选技能（仅启用中的），由父组件加载维护 */
  skills: SkillInfo[];
  onValueChange: (value: ComposerValue) => void;
  /** 菜单关闭且非输入法组合时按下 Enter */
  onSend: () => void;
  /** 浮层打开时触发（父组件可借此后台刷新技能列表） */
  onMenuOpen?: () => void;
}

/** 行首或空格后输入 / 触发（D:/work 这类路径不误触发） */
const SLASH_RE = /(?:^|\s)\/([a-zA-Z0-9_-]*)$/;

const CHIP_CLASS =
  'mx-0.5 inline-flex items-center rounded-full border border-indigo-200 bg-indigo-50 px-2 py-0.5 align-middle text-xs font-medium text-indigo-700';

interface MenuState {
  open: boolean;
  filter: string;
  active: number;
  /** 已注入为 chip 的技能名，列表中不再出现 */
  excluded: string[];
}

const MENU_CLOSED: MenuState = { open: false, filter: '', active: 0, excluded: [] };

function buildChip(name: string): HTMLSpanElement {
  const chip = document.createElement('span');
  chip.contentEditable = 'false';
  chip.dataset.skill = name;
  chip.className = CHIP_CLASS;
  chip.textContent = `✦ ${name}`;
  return chip;
}

/** 遍历编辑器 DOM，产出纯文本 / 技能名单 / 有序分段（纯派生，从不反解析） */
function serialize(el: HTMLElement): ComposerValue {
  const segments: SkillSegment[] = [];
  const skills: string[] = [];

  const walkChildren = (parent: Node) => {
    parent.childNodes.forEach(child => {
      if (child.nodeType === Node.TEXT_NODE) {
        segments.push({ type: 'text', text: (child as Text).data });
      } else if (child instanceof HTMLElement && child.dataset.skill !== undefined) {
        const name = child.dataset.skill;
        segments.push({ type: 'skill', name });
        if (!skills.includes(name)) skills.push(name);
      } else if (child.nodeName === 'BR') {
        segments.push({ type: 'text', text: '\n' });
      } else if (child.nodeType === Node.ELEMENT_NODE) {
        // 块级元素（div/p）非首子节点时边界视为换行；行内元素直接下钻
        const block = /^(DIV|P)$/.test(child.nodeName);
        if (block && child.previousSibling) segments.push({ type: 'text', text: '\n' });
        walkChildren(child);
      }
    });
  };
  walkChildren(el);

  // 合并相邻文本段、丢弃空段（编辑过程中会产生空文本节点）
  const merged: SkillSegment[] = [];
  for (const seg of segments) {
    if (seg.type === 'text') {
      if (!seg.text) continue;
      const last = merged[merged.length - 1];
      if (last?.type === 'text') last.text += seg.text;
      else merged.push({ ...seg });
    } else {
      merged.push(seg);
    }
  }

  return { text: joinSegments(merged), skills, segments: merged };
}

/**
 * contenteditable 输入区：支持 "/" 快捷插入 skill 占位符（行内 chip）。
 * 非受控——DOM 拥有内容，React 不回写子节点，值通过 onValueChange 上报。
 */
const SkillComposer = forwardRef<SkillComposerHandle, SkillComposerProps>(function SkillComposer(
  { placeholder, skills, onValueChange, onSend, onMenuOpen },
  ref,
) {
  const editorRef = useRef<HTMLDivElement>(null);
  const composingRef = useRef(false);
  const menuOpenRef = useRef(false);
  const suppressRef = useRef(false);
  const [menu, setMenu] = useState<MenuState>(MENU_CLOSED);

  const filtered = useMemo(() => {
    if (!menu.open) return [];
    const f = menu.filter.toLowerCase();
    return skills.filter(s => (!f || s.name.toLowerCase().includes(f)) && !menu.excluded.includes(s.name));
  }, [menu.open, menu.filter, menu.excluded, skills]);

  useEffect(() => {
    menuOpenRef.current = menu.open;
  }, [menu.open]);

  const emitValue = () => {
    const el = editorRef.current;
    if (el) onValueChange(serialize(el));
  };

  const resize = () => {
    const el = editorRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  };

  /** 光标前的纯文本（跨节点） */
  const textBeforeCaret = (): string => {
    const el = editorRef.current;
    const sel = window.getSelection();
    if (!el || !sel || sel.rangeCount === 0) return '';
    const caret = sel.getRangeAt(0);
    const r = document.createRange();
    r.selectNodeContents(el);
    r.setEnd(caret.endContainer, caret.endOffset);
    return r.toString();
  };

  /** 检查光标前文本是否以 "/" 开头的待补全片段；fromInput 表示由输入触发（可解除 Esc 抑制） */
  const detectSlash = (fromInput = false) => {
    if (suppressRef.current && !fromInput) return;
    if (fromInput) suppressRef.current = false;
    const m = SLASH_RE.exec(textBeforeCaret());
    if (!m) {
      setMenu(MENU_CLOSED);
      return;
    }
    const wasOpen = menuOpenRef.current;
    // 已注入的技能不再出现在候选列表；退格删掉 chip 后会随 input 事件重新计算
    const el = editorRef.current;
    const excluded = el
      ? Array.from(el.querySelectorAll<HTMLElement>('[data-skill]'), n => n.dataset.skill ?? '')
      : [];
    // 过滤串变化时高亮重置到首项，避免索引越过后指向已不存在的候选项
    setMenu(prev => ({ open: true, filter: m[1], active: prev.filter === m[1] ? prev.active : 0, excluded }));
    if (!wasOpen) onMenuOpen?.();
  };

  const handleInput = () => {
    const el = editorRef.current;
    if (el && (el.innerHTML === '<br>' || el.innerHTML === '<div><br></div>')) el.innerHTML = '';
    detectSlash(true);
    emitValue();
    resize();
  };

  const selectSkill = (skill: SkillInfo) => {
    const el = editorRef.current;
    const sel = window.getSelection();
    if (!el || !sel || sel.rangeCount === 0) return;
    el.focus();

    // 删除触发菜单的 "/过滤串"（都在当前文本节点内）
    const caret = sel.getRangeAt(0);
    if (caret.startContainer.nodeType === Node.TEXT_NODE && caret.collapsed) {
      const node = caret.startContainer as Text;
      const len = menu.filter.length + 1;
      const del = document.createRange();
      del.setStart(node, Math.max(0, caret.startOffset - len));
      del.setEnd(node, caret.startOffset);
      del.deleteContents();
      del.collapse(true);

      // 原位置插入 chip + 尾随空格，光标移到空格后
      // 用不间断空格：普通空格会被 Blink 的编辑命令当作可折叠空白吞掉，导致 chip 与后续文字粘连
      const space = document.createTextNode('\u00A0');
      del.insertNode(space);
      del.insertNode(buildChip(skill.name));
      const after = document.createRange();
      after.setStart(space, space.length);
      after.collapse(true);
      sel.removeAllRanges();
      sel.addRange(after);
    } else {
      const r = caret.cloneRange();
      r.collapse(true);
      r.insertNode(buildChip(skill.name));
    }

    setMenu(MENU_CLOSED);
    emitValue();
    resize();
  };

  /** 退格紧邻 chip 时整块删除（跨浏览器行为一致） */
  const handleBackspace = (e: React.KeyboardEvent) => {
    const el = editorRef.current;
    const sel = window.getSelection();
    if (!el || !sel || !sel.isCollapsed || sel.rangeCount === 0) return;
    const r = sel.getRangeAt(0);

    let prev: Node | null = null;
    if (r.startContainer.nodeType === Node.TEXT_NODE && r.startOffset === 0) {
      prev = r.startContainer.previousSibling;
    } else if (r.startContainer === el && r.startOffset > 0) {
      prev = r.startContainer.childNodes[r.startOffset - 1] ?? null;
    }
    if (prev instanceof HTMLElement && prev.dataset.skill !== undefined) {
      e.preventDefault();
      prev.remove();
      emitValue();
      resize();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (composingRef.current || e.nativeEvent.isComposing) return;

    if (menu.open && filtered.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setMenu(m => ({ ...m, active: (m.active + 1) % filtered.length }));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setMenu(m => ({ ...m, active: (m.active - 1 + filtered.length) % filtered.length }));
        return;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        selectSkill(filtered[Math.min(menu.active, filtered.length - 1)]);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        suppressRef.current = true;
        setMenu(MENU_CLOSED);
        return;
      }
    }

    if (e.key === 'Enter') {
      e.preventDefault();
      if (e.shiftKey) {
        document.execCommand('insertLineBreak');
        resize();
      } else {
        onSend();
      }
      return;
    }

    if (e.key === 'Backspace') handleBackspace(e);
  };

  // 过滤后无匹配项时自动关闭
  useEffect(() => {
    if (menu.open && filtered.length === 0) setMenu(MENU_CLOSED);
  }, [menu.open, filtered.length]);

  useImperativeHandle(ref, () => ({
    clear: () => {
      const el = editorRef.current;
      if (!el) return;
      el.innerHTML = '';
      setMenu(MENU_CLOSED);
      onValueChange({ text: '', skills: [], segments: [] });
      resize();
    },
    focus: () => editorRef.current?.focus(),
  }));

  return (
    <div className="relative">
      {menu.open && filtered.length > 0 && (
        <div className="nice-scroll absolute bottom-full left-0 right-0 z-20 mb-2 max-h-56 overflow-y-auto rounded-xl border border-zinc-200 bg-white py-1 shadow-lg">
          {filtered.map((s, i) => (
            <button
              key={s.name}
              className={`flex w-full items-start gap-2 px-3 py-2 text-left text-sm transition-colors ${
                i === menu.active ? 'bg-indigo-50' : 'hover:bg-zinc-50'
              }`}
              onMouseDown={e => e.preventDefault()}
              onClick={() => selectSkill(s)}
              ref={i === menu.active ? node => node?.scrollIntoView({ block: 'nearest' }) : undefined}
            >
              <span className="mt-0.5 shrink-0 text-indigo-500">✦</span>
              <span className="min-w-0">
                <span className="block truncate font-medium text-zinc-700">{s.name}</span>
                {s.description && (
                  <span className="block truncate text-xs text-zinc-400">{s.description}</span>
                )}
              </span>
            </button>
          ))}
          <div className="border-t border-zinc-100 px-3 py-1.5 text-[11px] text-zinc-400">
            ↑↓ 选择 · Enter 确认 · Esc 关闭
          </div>
        </div>
      )}
      <div
        ref={editorRef}
        contentEditable
        suppressContentEditableWarning
        role="textbox"
        aria-multiline="true"
        data-placeholder={placeholder}
        className="nice-scroll block min-h-[42px] w-full resize-none overflow-y-auto bg-transparent px-4 pt-3 pb-1 text-sm leading-relaxed outline-none empty:before:text-zinc-400 empty:before:content-[attr(data-placeholder)]"
        onInput={handleInput}
        onKeyDown={handleKeyDown}
        onKeyUp={() => detectSlash()}
        onMouseUp={() => detectSlash()}
        onBlur={() => setMenu(MENU_CLOSED)}
        onPaste={e => {
          e.preventDefault();
          document.execCommand('insertText', false, e.clipboardData.getData('text/plain'));
        }}
        onCompositionStart={() => {
          composingRef.current = true;
          setMenu(MENU_CLOSED);
        }}
        onCompositionEnd={() => {
          composingRef.current = false;
          detectSlash();
          emitValue();
          resize();
        }}
      />
    </div>
  );
});

export default SkillComposer;
