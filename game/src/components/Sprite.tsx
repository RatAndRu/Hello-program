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
