import { useEffect, useId, useRef, useState } from "react";
import { searchPlaces } from "../lib/api";

/** Autocomplete over the backend's place search. `value` is the chosen place
 * ({label, lat, lon}) or null while the user is typing. */
export default function PlaceInput({ label, icon, value, onChange, placeholder }) {
  const id = useId();
  const [text, setText] = useState(value?.label ?? "");
  const [options, setOptions] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const typed = useRef(false);

  // sync only when a place is chosen from outside (e.g. an example chip);
  // value becoming null means the user is editing, so keep their text
  useEffect(() => {
    if (!value) return;
    typed.current = false;
    setText(value.label);
  }, [value]);

  useEffect(() => {
    if (!typed.current || text.trim().length < 2) {
      setOptions([]);
      return;
    }
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      searchPlaces(text, ctrl.signal)
        .then((r) => {
          setOptions(r);
          setActive(0);
          setOpen(true);
        })
        .catch(() => {});
    }, 300);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [text]);

  const choose = (place) => {
    typed.current = false;
    onChange(place);
    setOpen(false);
  };

  const onKeyDown = (e) => {
    if (!open || !options.length) return;
    if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, options.length - 1));
    else if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
    else if (e.key === "Enter") choose(options[active]);
    else if (e.key === "Escape") setOpen(false);
    else return;
    e.preventDefault();
  };

  const listOpen = open && options.length > 0;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="with-icon">
        <span className="pin" aria-hidden="true">{icon}</span>
        <input
          id={id}
          value={text}
          placeholder={placeholder}
          onChange={(e) => {
            typed.current = true;
            setText(e.target.value);
            if (value) onChange(null);
          }}
          onKeyDown={onKeyDown}
          onFocus={() => options.length && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          role="combobox"
          aria-expanded={listOpen}
          aria-autocomplete="list"
          aria-controls={`${id}-list`}
          aria-activedescendant={listOpen ? `${id}-opt-${active}` : undefined}
          autoComplete="off"
          required
        />
      </div>
      {listOpen && (
        <ul className="suggestions" role="listbox" id={`${id}-list`}>
          {options.map((o, i) => (
            <li
              key={`${o.label}${o.lat}`}
              id={`${id}-opt-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : ""}
              onMouseDown={() => choose(o)}
            >
              {o.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
