import type { SpriteName } from "../model";

export function Sprite({
  name,
  className = "",
  src,
}: {
  name: SpriteName;
  className?: string;
  src?: string;
}) {
  if (src)
    return (
      <img
        className={`sprite custom-sprite ${className}`}
        src={src}
        alt=""
        draggable={false}
      />
    );
  return (
    <svg
      className={`sprite ${className}`}
      data-sprite={name}
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden="true"
      shapeRendering="crispEdges"
    >
      {name === "hero" && (
        <>
          <ellipse
            cx="32"
            cy="57"
            rx="17"
            ry="5"
            fill="#173c32"
            opacity=".22"
          />
          <path d="M21 43h9v13h-11v-5h2zm14 0h9v8h2v5H34z" fill="#493c37" />
          <path d="M19 29h26v18H19z" fill="#477b8b" />
          <path d="M15 32h7v14h-7zm27 0h7v14h-7z" fill="#efc397" />
          <path d="M22 14h20v19H22z" fill="#f3c99e" />
          <path d="M19 14h5v12h-5zm20 0h6v8h-6z" fill="#664737" />
          <path d="M23 9h17v5h7v6H17v-6h6z" fill="#d89e51" />
          <path d="M24 7h14v7H24z" fill="#ebbd6a" />
          <path d="M16 18h33v5H16z" fill="#f0c677" />
          <path d="M27 25h3v4h-3zm10 0h3v4h-3z" fill="#304139" />
          <path d="M30 32h7v2h-7z" fill="#c58468" />
          <path d="M22 35h20v5H22z" fill="#e6b85d" />
          <path d="M35 39h6v9h-6z" fill="#dcaa50" />
          <path d="M22 46h20v4H22z" fill="#355866" />
        </>
      )}
      {name === "gardener" && (
        <>
          <ellipse cx="32" cy="57" rx="18" ry="5" fill="#173c32" opacity=".2" />
          <path d="M21 45h10v12H19v-5h2zm14 0h10v7h2v5H35z" fill="#5b493b" />
          <path d="M19 29h27v20H19z" fill="#809565" />
          <path d="M25 31h15v21H25z" fill="#a87953" />
          <path d="M15 33h7v13h-7zm28 0h7v13h-7z" fill="#e7bc91" />
          <path d="M22 15h22v17H22z" fill="#efc79c" />
          <path d="M23 27h20v9H23z" fill="#e8e2cb" />
          <path d="M27 32h12v7H27z" fill="#d6d2bd" />
          <path d="M27 23h3v3h-3zm10 0h3v3h-3z" fill="#3f4938" />
          <path d="M21 9h23v9H21z" fill="#b98c51" />
          <path d="M16 16h34v6H16z" fill="#e3bc70" />
          <path d="M22 14h21v4H22z" fill="#7c8e58" />
          <path d="M49 31h3v26h-3z" fill="#806244" />
          <path d="M46 28h9v7h-9z" fill="#aeb8a7" />
        </>
      )}
      {name === "slime" && (
        <>
          <ellipse cx="32" cy="54" rx="23" ry="6" fill="#234939" opacity=".2" />
          <path
            d="M13 34h5v-9h8v-5h15v5h7v9h5v16h-7v5H20v-5h-7z"
            fill="#78ad75"
          />
          <path d="M18 34h5v-7h17v5H29v7H18z" fill="#a9d490" />
          <path d="M23 37h5v6h-5zm15 0h5v6h-5z" fill="#294e43" />
          <path d="M29 47h9v3h-9z" fill="#3e7354" />
          <path d="M15 45h5v5h-5zm33-8h5v8h-5z" fill="#659964" />
          <path d="M30 16h5v7h-5zm5-5h8v5h-8z" fill="#6d9852" />
        </>
      )}
      {name === "apple" && (
        <>
          <ellipse
            cx="32"
            cy="54"
            rx="16"
            ry="4"
            fill="#234939"
            opacity=".18"
          />
          <path
            d="M19 25h10v3h7v-3h10v5h5v17h-5v6H20v-6h-5V31h4z"
            fill="#d96d53"
          />
          <path d="M21 29h8v5h-5v9h-5V32h2z" fill="#f39b75" />
          <path d="M31 16h4v13h-4z" fill="#796047" />
          <path d="M35 15h12v6H35z" fill="#749956" />
          <path d="M43 39h7v8h-7z" fill="#bd5546" />
        </>
      )}
      {name === "berry" && (
        <>
          <ellipse
            cx="32"
            cy="53"
            rx="18"
            ry="4"
            fill="#234939"
            opacity=".18"
          />
          <path d="M28 17h5v17h-5z" fill="#657b43" />
          <path d="M17 16h13v7H17zm17-5h14v7H34z" fill="#7c9b56" />
          <path
            d="M15 31h17v17H15zm17-4h18v18H32zm-8 16h18v13H24z"
            fill="#9c739e"
          />
          <path d="M18 33h6v5h-6zm17-3h6v5h-6zm-8 16h6v5h-6z" fill="#c9a1bf" />
        </>
      )}
      {name === "key" && (
        <>
          <path d="M15 14h20v5h5v19h-7v7h-7v7h-9v-9h6v-7h-8z" fill="#d7aa4e" />
          <path d="M21 20h10v10H21z" fill="#faf0cc" />
          <path d="M18 15h16v4H18zm7 24h7v6h-7z" fill="#f2cc70" />
        </>
      )}
      {name === "coin" && (
        <>
          <ellipse
            cx="32"
            cy="54"
            rx="16"
            ry="4"
            fill="#234939"
            opacity=".16"
          />
          <path d="m32 9 16 17-5 21-11 9-13-12-4-18z" fill="#8abfc1" />
          <path d="m32 9 3 23-20-6z" fill="#d1f1df" />
          <path d="m35 32 13-6-5 21-11 9z" fill="#5a9eac" />
          <path d="m32 9 16 17-13 6z" fill="#a8dbd1" />
        </>
      )}
      {name === "chest" && (
        <>
          <ellipse cx="32" cy="54" rx="25" ry="5" fill="#234939" opacity=".2" />
          <path d="M9 25h46v28H9z" fill="#9d6c42" />
          <path d="M14 16h36v5h5v12H9V21h5z" fill="#bb8a50" />
          <path d="M10 31h44v5H10z" fill="#694b37" />
          <path d="M15 18h5v34h-5zm29 0h5v34h-5z" fill="#dfb65e" />
          <path d="M27 30h11v13H27z" fill="#e7c56b" />
          <path d="M31 34h3v5h-3z" fill="#785a3b" />
          <path d="M10 49h44v4H10z" fill="#775033" />
        </>
      )}
      {name === "gate" && (
        <>
          <path d="M8 15h10v42H8zm38 0h10v42H46z" fill="#8d967e" />
          <path d="M6 11h14v8H6zm38 0h14v8H46z" fill="#b4b9a0" />
          <path d="M18 23h28v5H18zm0 20h28v5H18z" fill="#9b794e" />
          <path d="M20 20h5v34h-5zm9 0h5v34h-5zm9 0h5v34h-5z" fill="#b8955f" />
          <path d="M28 32h9v10h-9z" fill="#d8b559" />
        </>
      )}
      {name === "sword" && (
        <>
          <path d="M43 8h12v12L29 45 19 35z" fill="#b9ced0" />
          <path d="M48 12h4L25 40h-4z" fill="#e7f0e8" />
          <path d="m15 29 21 21-5 5-21-21z" fill="#d9b25d" />
          <path d="m17 43 6 6-9 10H8v-6z" fill="#8b654b" />
        </>
      )}
      {name === "flower" && (
        <>
          <path d="M30 30h4v25h-4z" fill="#62864e" />
          <path d="M20 39h10v6H20zm14-7h11v6H34z" fill="#86a561" />
          <path d="M25 12h14v10h10v14H39v10H25V36H15V22h10z" fill="#f3d48a" />
          <path d="M26 24h12v11H26z" fill="#d59b58" />
        </>
      )}
      {name === "sign" && (
        <>
          <path d="M29 28h7v29h-7z" fill="#856541" />
          <path d="M9 14h43v23H9z" fill="#bd955d" />
          <path d="M12 17h37v4H12z" fill="#d9b779" />
          <path d="M18 25h25v3H18zm19-4h6v11h-6z" fill="#806847" />
        </>
      )}
      {name === "knight" && (
        <>
          <ellipse
            cx="32"
            cy="57"
            rx="17"
            ry="5"
            fill="#173c32"
            opacity=".22"
          />
          <path d="M21 44h9v12H19v-4h2zm13 0h9v8h2v4H34z" fill="#4b4f5c" />
          <path d="M19 26h26v20H19z" fill="#7b8797" />
          <path d="M23 28h18v6H23z" fill="#a9b5c2" />
          <path d="M15 29h7v15h-7zm27 0h7v15h-7z" fill="#9aa6b3" />
          <path d="M22 12h20v16H22z" fill="#b9c3cc" />
          <path d="M25 6h14v7H25z" fill="#8f9caa" />
          <path d="M27 17h3v4h-3zm8 0h3v4h-3z" fill="#2d3a44" />
          <path d="M22 22h20v4H22z" fill="#5d6a76" />
          <path d="M30 24h4v14h-4z" fill="#c9d3d8" />
          <path d="M22 38h20v5H22z" fill="#6f7c88" />
          <path d="M48 22h3v26h-3z" fill="#8a6a4a" />
          <path d="M46 18h7v6h-7z" fill="#aeb8c2" />
        </>
      )}
      {name === "knight-gold" && (
        <>
          <ellipse
            cx="32"
            cy="57"
            rx="17"
            ry="5"
            fill="#173c32"
            opacity=".22"
          />
          <path d="M21 44h9v12H19v-4h2zm13 0h9v8h2v4H34z" fill="#5b4a2f" />
          <path d="M19 26h26v20H19z" fill="#c8a05a" />
          <path d="M23 28h18v6H23z" fill="#ecd28b" />
          <path d="M15 29h7v15h-7zm27 0h7v15h-7z" fill="#d8b56f" />
          <path d="M22 12h20v16H22z" fill="#e8cf92" />
          <path d="M25 6h14v7H25z" fill="#c09c55" />
          <path d="M27 17h3v4h-3zm8 0h3v4h-3z" fill="#4a3a24" />
          <path d="M22 22h20v4H22z" fill="#a9843f" />
          <path d="M30 24h4v14h-4z" fill="#f4e6b8" />
          <path d="M22 38h20v5H22z" fill="#96743a" />
          <path d="M16 8h32v5H16z" fill="#d6b166" />
          <path d="M20 4h5v6h-5zm19 0h5v6h-5z" fill="#b08f4c" />
        </>
      )}
      {name === "knight-dark" && (
        <>
          <ellipse
            cx="32"
            cy="57"
            rx="18"
            ry="5"
            fill="#1d2a2c"
            opacity=".28"
          />
          <path d="M20 44h10v12H18v-4h2zm14 0h10v8h2v4H34z" fill="#2b2a33" />
          <path d="M18 25h28v21H18z" fill="#3f414f" />
          <path d="M22 27h20v6H22z" fill="#5b5f70" />
          <path d="M14 28h7v16h-7zm29 0h7v16h-7z" fill="#4a4c5b" />
          <path d="M21 11h22v17H21z" fill="#4d5060" />
          <path d="M23 5h18v8H23z" fill="#33353f" />
          <path d="M18 8h10v4H18zm22 0h10v4H40z" fill="#6b5a8c" />
          <path d="M26 17h4v4h-4zm9 0h4v4h-4z" fill="#c4789a" />
          <path d="M30 24h4v15h-4z" fill="#6f6f86" />
          <path d="M21 38h22v5H21z" fill="#2d2d38" />
          <path d="M48 20h3v28h-3z" fill="#3a3547" />
          <path d="M45 16h9v6h-9z" fill="#6f5d93" />
        </>
      )}
      {name === "lantern" && (
        <>
          <ellipse cx="32" cy="57" rx="12" ry="4" fill="#234939" opacity=".2" />
          <path d="M29 40h6v18h-6z" fill="#5b5148" />
          <path d="M22 46h20v4H22z" fill="#6f6255" />
          <path d="M21 18h22v21H21z" fill="#f0c968" opacity=".22" />
          <path d="M23 14h18v4H23z" fill="#6f6255" />
          <path d="M25 18h14v19H25z" fill="#f7dd9a" />
          <path d="M28 21h8v13h-8z" fill="#fff6cf" />
          <path d="M30 24h4v7h-4z" fill="#f6b95f" />
          <path d="M23 37h18v4H23z" fill="#5b5148" />
          <path d="M30 4h4v10h-4z" fill="#6f6255" />
          <path d="M25 8h14v3H25z" fill="#877565" />
          <path d="M18 30h3v6h-3zm25 0h3v6h-3z" fill="#f3cd7c" opacity=".55" />
        </>
      )}
      {name === "castle" && (
        <>
          <ellipse
            cx="32"
            cy="58"
            rx="27"
            ry="5"
            fill="#1d2a2c"
            opacity=".22"
          />
          <path d="M6 56h52v6H6z" fill="#5e6068" />
          <path d="M10 26h44v30H10z" fill="#7d8089" />
          <path d="M10 26h44v5H10z" fill="#9a9da6" />
          <path
            d="M14 14h8v12h-8zm18-6h8v18h-8zm18 6h8v12h-8z"
            fill="#8d9099"
          />
          <path d="M14 10h8v5h-8zm18-6h8v5h-8zm18 6h8v5h-8z" fill="#a7aab2" />
          <path d="M6 20h10v34H6zm42 0h10v34H52z" fill="#6f727b" />
          <path
            d="M6 16h3v6H6zm4 0h3v6H10zm42 0h3v6h-3zm4 0h3v6h-3z"
            fill="#9a9da6"
          />
          <path d="M28 40h9v16h-9z" fill="#4e4a48" />
          <path d="M30 43h5v13h-5z" fill="#f0c968" />
          <path d="M18 33h6v7h-6zm20 0h6v7h-6z" fill="#f7dd9a" />
          <path d="M19 34h4v5h-4zm20 0h4v5h-4z" fill="#fff4c9" />
          <path d="M30 4h4v12h-4z" fill="#8a6a4a" />
          <path d="M34 5h13v5H34z" fill="#b8564e" />
        </>
      )}
      {name === "banner" && (
        <>
          <path d="M28 10h4v44h-4z" fill="#7a5c40" />
          <path d="M32 12h22v20l-11 6-11-6z" fill="#b8564e" />
          <path d="M35 16h16v4H35zm0 8h16v4H35z" fill="#d9796a" />
          <path d="M40 24h6v6h-6z" fill="#f3e2a8" />
          <path d="M30 8h26v5H30z" fill="#8a6a4a" />
        </>
      )}
      {name === "fountain" && (
        <>
          <ellipse
            cx="32"
            cy="57"
            rx="25"
            ry="5"
            fill="#234939"
            opacity=".18"
          />
          <path d="M9 40h46v12H9z" fill="#9097a2" />
          <path d="M12 36h40v6H12z" fill="#b3bac4" />
          <path d="M14 44h36v5H14z" fill="#7f9fb0" />
          <path d="M26 26h12v12H26z" fill="#9aa3ad" />
          <path d="M24 22h16v5H24z" fill="#bcc3cb" />
          <path d="M30 12h4v12h-4z" fill="#cfe6ea" />
          <path d="M22 14h4v8h-4zm16 0h4v8h-4z" fill="#bfe0e6" />
          <path d="M18 30h3v6h-3zm25 0h3v6h-3z" fill="#e3f4f4" opacity=".8" />
        </>
      )}
      {name === "ember" && (
        <>
          <ellipse
            cx="32"
            cy="54"
            rx="16"
            ry="4"
            fill="#234939"
            opacity=".16"
          />
          <path
            d="M30 12h6v10h5v6h5v14h-5v6H24v-6h-5V30h5v-6h6z"
            fill="#f2a94e"
          />
          <path d="M27 26h5v-6h5v10h4v12H27z" fill="#ffd98a" />
          <path d="M30 31h5v9h-5z" fill="#fff6cf" />
          <path d="M20 22h3v3h-3zm22 5h3v3h-3z" fill="#f7cd7a" opacity=".8" />
        </>
      )}
      {name === "rem" && (
        <>
          <ellipse
            cx="32"
            cy="57"
            rx="17"
            ry="5"
            fill="#173c32"
            opacity=".22"
          />
          <path d="M21 45h10v12H19v-4h2zm14 0h10v7h2v5H35z" fill="#3e3a48" />
          <path d="M19 28h26v19H19z" fill="#2f2c3a" />
          <path d="M25 26h14v22H25z" fill="#f4f2f6" />
          <path d="M22 28h5v10h-5zm18 0h5v10h-5z" fill="#fffafa" />
          <path d="M14 30h7v14h-7zm29 0h7v14h-7z" fill="#f7dccd" />
          <path d="M23 14h18v16H23z" fill="#fbe6d8" />
          <path d="M21 12h22v6H21z" fill="#bcd9ee" />
          <path d="M18 16h8v15h-8z" fill="#a9cbe4" />
          <path d="M40 16h6v13h-6z" fill="#a9cbe4" />
          <path d="M25 20h4v4h-4zm7 0h4v4h-4z" fill="#4b6f8f" />
          <path d="M28 29h6v2h-6z" fill="#d99c92" />
          <path d="M25 22h12v3H25z" fill="#d6e8f4" />
          <path d="M38 8h6v10h-6z" fill="#c3dcee" />
          <path d="M22 30h20v4H22z" fill="#f6f4f8" />
          <path d="M30 34h5v9h-5z" fill="#dcd6e6" />
        </>
      )}
      {name === "ram" && (
        <>
          <ellipse
            cx="32"
            cy="57"
            rx="17"
            ry="5"
            fill="#173c32"
            opacity=".22"
          />
          <path d="M21 45h10v12H19v-4h2zm14 0h10v7h2v5H35z" fill="#3e3a48" />
          <path d="M19 28h26v19H19z" fill="#312d3b" />
          <path d="M25 26h14v22H25z" fill="#f6f3f7" />
          <path d="M22 28h5v10h-5zm18 0h5v10h-5z" fill="#fffafa" />
          <path d="M14 30h7v14h-7zm29 0h7v14h-7z" fill="#f7dccd" />
          <path d="M23 14h18v16H23z" fill="#fbe6d8" />
          <path d="M21 12h22v6H21z" fill="#f2bccb" />
          <path d="M14 17h7v16h-7z" fill="#eab0c3" />
          <path d="M41 17h6v14h-6z" fill="#eab0c3" />
          <path d="M25 20h4v4h-4zm7 0h4v4h-4z" fill="#c2607a" />
          <path d="M28 29h6v2h-6z" fill="#d99c92" />
          <path d="M25 22h12v3H25z" fill="#fbe4ea" />
          <path d="M30 8h5v11h-5z" fill="#eea9bd" />
          <path d="M22 30h20v4H22z" fill="#fbf6f8" />
          <path d="M30 34h5v9h-5z" fill="#e6c9d6" />
          <path d="M24 38h8v4h-8z" fill="#d95f78" opacity=".8" />
        </>
      )}
      {name === "emilia" && (
        <>
          <ellipse
            cx="32"
            cy="57"
            rx="18"
            ry="5"
            fill="#173c32"
            opacity=".22"
          />
          <path d="M21 46h10v11H19v-4h2zm14 0h10v7h2v4H35z" fill="#44496b" />
          <path d="M19 28h26v20H19z" fill="#5d6494" />
          <path d="M24 27h16v22H24z" fill="#f2f5fb" />
          <path d="M14 31h7v13h-7zm29 0h7v13h-7z" fill="#f9e2d4" />
          <path d="M23 13h18v16H23z" fill="#fdeade" />
          <path d="M20 11h24v7H20z" fill="#e9eefb" />
          <path d="M15 16h8v20h-8z" fill="#dde5f8" />
          <path d="M41 16h8v20h-8z" fill="#dde5f8" />
          <path d="M24 20h5v4h-5zm7 0h5v4h-5z" fill="#7c5fa8" />
          <path d="M28 29h7v2h-7z" fill="#e0a193" />
          <path d="M26 24h13v2H26z" fill="#f6f9ff" />
          <path d="M30 34h5v10h-5z" fill="#e6eaf8" />
          <path d="M13 6h3v10h-3zm36 4h3v10h-3z" fill="#bcdcf0" />
          <path d="M22 39h20v4H22z" fill="#4b5077" />
        </>
      )}
      {name === "puck" && (
        <>
          <ellipse
            cx="32"
            cy="55"
            rx="16"
            ry="4"
            fill="#234939"
            opacity=".18"
          />
          <path d="M18 44h4v6h-4zm24 0h4v6h-4z" fill="#cfd8dd" />
          <path d="M17 28h30v18H17z" fill="#e3e9ec" />
          <path d="M21 22h22v10H21z" fill="#eef3f5" />
          <path d="M17 25h9V15h6v10h6V13h7v12h7v9H17z" fill="#dbe3e7" />
          <path d="M24 26h5v5h-5zm11 0h5v5h-5z" fill="#5c7f9c" />
          <path d="M31 33h3v3h-3z" fill="#c08a97" />
          <path d="M26 38h12v3H26z" fill="#cdd7dc" />
          <path d="M45 40h10v4H45z" fill="#dbe3e7" />
          <path d="M52 36h3v12h-3z" fill="#cdd7dc" />
          <path d="M36 6h3v6h-3z" fill="#9fb6c4" />
          <path d="M41 4h2v3h-2z" fill="#bcd6e2" />
        </>
      )}
      {name === "roswaal" && (
        <>
          <ellipse
            cx="32"
            cy="57"
            rx="17"
            ry="5"
            fill="#173c32"
            opacity=".22"
          />
          <path d="M22 45h8v12H20v-4h2zm12 0h9v7h2v5H34z" fill="#3b2f45" />
          <path d="M19 27h26v20H19z" fill="#584a6e" />
          <path d="M25 26h14v22H25z" fill="#f0e7cf" />
          <path d="M14 30h7v14h-7zm29 0h7v14h-7z" fill="#f2d6c4" />
          <path d="M23 12h18v16H23z" fill="#f8e2d2" />
          <path d="M20 10h24v6H20z" fill="#7f4b8e" />
          <path d="M15 14h7v16h-7z" fill="#a44f6d" />
          <path d="M42 14h7v16h-7z" fill="#a44f6d" />
          <path d="M25 19h4v4h-4zm7 0h4v4h-4z" fill="#5d6f8c" />
          <path d="M28 28h7v2h-7z" fill="#c99083" />
          <path d="M31 6h5v7h-5z" fill="#c86a8e" />
          <path d="M22 39h20v4H22z" fill="#4a3d5c" />
          <path d="M35 30h9v9h-9z" fill="#f2f5f7" opacity=".7" />
        </>
      )}
      {name === "rose" && (
        <>
          <ellipse
            cx="32"
            cy="55"
            rx="13"
            ry="4"
            fill="#234939"
            opacity=".16"
          />
          <path d="M30 30h4v24h-4z" fill="#4f7a4a" />
          <path d="M22 42h10v4H22zm12-6h10v4H34z" fill="#628f56" />
          <path
            d="M33 26h3v-2h4v2h4v4h2v8h-2v4H25v-4h-2v-8h2v-4h4v-2h4z"
            fill="#c2455c"
          />
          <path d="M28 26h9v5h5v8H28z" fill="#dd6a7b" />
          <path d="M30 28h6v6h-6z" fill="#f0a3ae" />
          <path d="M31 36h6v5h-6z" fill="#b84057" />
          <path d="M39 14h4v6h-4z" fill="#4f7a4a" />
        </>
      )}
      {name === "ice" && (
        <>
          <ellipse
            cx="32"
            cy="55"
            rx="14"
            ry="4"
            fill="#234939"
            opacity=".16"
          />
          <path d="m32 7 14 20-14 26-14-26z" fill="#9fd4ec" />
          <path d="m32 7 14 20-14 8z" fill="#d8f1fa" />
          <path d="M32 27 46 27l-14 26z" fill="#6fb4d4" />
          <path d="m32 7-14 20 14 8z" fill="#bfe6f4" />
          <path d="M30 18h3v9h-3z" fill="#ffffff" opacity=".7" />
          <path d="M18 40h4v4h-4zm24 4h3v3h-3z" fill="#e6f7fc" opacity=".8" />
        </>
      )}
      {name === "contract" && (
        <>
          <ellipse
            cx="32"
            cy="54"
            rx="15"
            ry="4"
            fill="#234939"
            opacity=".16"
          />
          <path d="M22 12h20v34H22z" fill="#f6efd8" />
          <path d="M22 12h20v5H22z" fill="#e3d7b4" />
          <path d="M27 22h10v2H27zm0 5h10v2H27zm0 5h7v2h-7z" fill="#b5a883" />
          <path d="M34 40h8v8h-8z" fill="#8aa8c9" />
          <path d="M35 41h6v6h-6z" fill="#dfeffb" />
          <path d="M16 16h4v4h-4zm24 0h4v4h-4z" fill="#f0c968" />
          <path d="M20 46h6v4h-6zm18 4h6v4h-6z" fill="#e6dcbd" />
        </>
      )}
      {name === "tree" && (
        <>
          <ellipse
            cx="32"
            cy="58"
            rx="24"
            ry="5"
            fill="#234939"
            opacity=".18"
          />
          <path d="M27 35h12v23H27z" fill="#876848" />
          <path d="M32 38h7v20h-7z" fill="#6e573e" />
          <path
            d="M22 5h20v7h9v10h7v19h-8v8H15v-8H7V23h7V12h8z"
            fill="#477957"
          />
          <path d="M22 5h20v7h9v10h-9v8H19v-7h-5V12h8z" fill="#659362" />
          <path d="M23 9h15v6H23zm-5 8h12v6H18z" fill="#7ba36c" />
          <path d="M15 36h13v6h15v7H15z" fill="#3b6b4e" />
        </>
      )}
    </svg>
  );
}
