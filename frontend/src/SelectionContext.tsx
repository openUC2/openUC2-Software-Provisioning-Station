import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, type CachedVersion, type MatchedFirmware } from "./api";

/**
 * The station-wide "what are we building right now" selection.
 *
 * Picking an SD card image also decides which ESP32 firmware is allowed:
 * the os-rpi deployment files pin an exact firmware-image-server container,
 * and that container is the only firmware that matches the image.  Holding
 * that selection here keeps the SD page, the ESP page and the test pages in
 * agreement instead of each having its own idea of "latest".
 */
interface SelectionState {
  imageVersion: string | null;
  setImageVersion: (v: string | null) => void;
  image: CachedVersion | null;
  matched: MatchedFirmware | null;
  /** Ignore the pairing and allow any cached firmware bundle. */
  unlocked: boolean;
  setUnlocked: (v: boolean) => void;
  images: CachedVersion[];
  refresh: () => Promise<void>;
}

const SelectionContext = createContext<SelectionState | null>(null);
const STORAGE_KEY = "uc2.selectedImage";

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [imageVersion, setImageVersionRaw] = useState<string | null>(
    () => localStorage.getItem(STORAGE_KEY),
  );
  const [unlocked, setUnlocked] = useState(false);
  const [images, setImages] = useState<CachedVersion[]>([]);

  const refresh = useCallback(async () => {
    try {
      const res = await api.images(false);
      const complete = res.cached.filter((v) => v.complete);
      setImages(complete);
      // Default to the newest cached image, and drop a selection whose
      // image has since been deleted from the cache.
      setImageVersionRaw((cur) => {
        if (cur && complete.some((v) => v.version_id === cur)) return cur;
        return complete[0]?.version_id ?? null;
      });
    } catch {
      /* keep last known */
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  const setImageVersion = useCallback((v: string | null) => {
    setImageVersionRaw(v);
    if (v) localStorage.setItem(STORAGE_KEY, v);
    else localStorage.removeItem(STORAGE_KEY);
  }, []);

  const value = useMemo<SelectionState>(() => {
    const image = images.find((v) => v.version_id === imageVersion) ?? null;
    return {
      imageVersion,
      setImageVersion,
      image,
      matched: (image?.matched_firmware as MatchedFirmware | undefined) ?? null,
      unlocked,
      setUnlocked,
      images,
      refresh,
    };
  }, [imageVersion, images, setImageVersion, unlocked, refresh]);

  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
}

export function useSelection(): SelectionState {
  const ctx = useContext(SelectionContext);
  if (!ctx) throw new Error("useSelection must be used inside <SelectionProvider>");
  return ctx;
}
