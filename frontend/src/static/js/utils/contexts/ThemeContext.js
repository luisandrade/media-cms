import React, { createContext, useContext, useEffect, useState } from 'react';
import { BrowserCache } from '../classes/';
import { addClassname, removeClassname, supportsSvgAsImg } from '../helpers/';
import { config as mediacmsConfig } from '../settings/config.js';
import SiteContext from './SiteContext';

const config = mediacmsConfig(window.MediaCMS);

function initLogo(logo) {
  let light = null;
  let dark = null;

  if (void 0 !== logo.darkMode) {
    if (supportsSvgAsImg() && void 0 !== logo.darkMode.png && '' !== logo.darkMode.png) {
      dark = logo.darkMode.png;
    } else if (void 0 !== logo.darkMode.img && '' !== logo.darkMode.img) {
      dark = logo.darkMode.img;
    }
  }

  if (void 0 !== logo.lightMode) {
    if (supportsSvgAsImg() && void 0 !== logo.lightMode.png && '' !== logo.lightMode.png) {
      light = logo.lightMode.png;
    } else if (void 0 !== logo.lightMode.img && '' !== logo.lightMode.img) {
      light = logo.lightMode.img;
    }
  }

  if (null !== light || null !== dark) {
    if (null === light) {
      light = dark;
    } else if (null === dark) {
      dark = light;
    }
  }

  return {
    light,
    dark,
  };
}

function initMode(cachedValue, defaultValue) {
  return 'light' === cachedValue || 'dark' === cachedValue ? cachedValue : defaultValue;
}

export const ThemeContext = createContext();

export const ThemeProvider = ({ children }) => {
  const site = useContext(SiteContext);
  const cache = new BrowserCache('MediaCMS[' + site.id + '][theme]', 86400);
  const [themeMode, setThemeMode] = useState(initMode(cache.get('mode'), config.theme.mode));
  const logos = initLogo(config.theme.logo);
  const [logo, setLogo] = useState(logos[themeMode]);

  const changeMode = () => {
    setThemeMode('light' === themeMode ? 'dark' : 'light');
  };

  useEffect(() => {
    if ('dark' === themeMode) {
      addClassname(document.body, 'dark_theme');
    } else {
      removeClassname(document.body, 'dark_theme');
    }
    cache.set('mode', themeMode);
    setLogo(logos[themeMode]);
  }, [themeMode]);

  const value = {
    logo,
    currentThemeMode: themeMode,
    changeThemeMode: changeMode,
    themeModeSwitcher: config.theme.switch,
  };

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
};

export const ThemeConsumer = ThemeContext.Consumer;
