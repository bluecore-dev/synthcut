import { useEffect } from "react";
import { useNavigate } from "react-router";
import { backButton } from "../telegram";

/** Shows Telegram's native back button while the calling screen is mounted. */
export function useBackButton(to: string | number = -1) {
  const navigate = useNavigate();
  useEffect(() => {
    const bb = backButton();
    if (!bb) return;
    const go = () => (typeof to === "number" ? navigate(to) : navigate(to));
    bb.onClick(go);
    bb.show();
    return () => {
      bb.offClick(go);
      bb.hide();
    };
  }, [navigate, to]);
}
