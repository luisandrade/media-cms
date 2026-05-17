import React, { useRef, useEffect } from 'react';
import PropTypes from 'prop-types';
import urlParse from 'url-parse';

import videojs from 'video.js';
import 'videojs-contrib-quality-levels';
import 'videojs-http-source-selector';

import './VideoPlayer.scss';

export function formatInnerLink(url, baseUrl) {
  let link = urlParse(url, {});
  if ('' === link.origin || 'null' === link.origin || !link.origin) {
    link = urlParse(baseUrl + '/' + url.replace(/^\//g, ''), {});
  }
  return link.toString();
}

export function VideoPlayerError(props) {
  return (
    <div className="error-container">
      <div className="error-container-inner">
        <span className="icon-wrap">
          <i className="material-icons">error_outline</i>
        </span>
        <span className="msg-wrap">{props.errorMessage}</span>
      </div>
    </div>
  );
}

VideoPlayerError.propTypes = {
  errorMessage: PropTypes.string.isRequired,
};

function inferVideoSourceType(url) {
  const normalizedUrl = (url ?? '').toString().split('?')[0].toLowerCase();

  if (normalizedUrl.endsWith('.m3u8')) {
    return 'application/x-mpegURL';
  }

  if (normalizedUrl.endsWith('.mp4')) {
    return 'video/mp4';
  }

  if (normalizedUrl.endsWith('.webm')) {
    return 'video/webm';
  }

  return 'application/x-mpegURL';
}

export function VideoPlayer(props) {
  console.log("props player embed", props);
  const videoElemRef = useRef(null);
  const playerRef = useRef(null);
  const vodUiObserverRef = useRef(null);
  const vodUiTimeoutsRef = useRef([]);

  useEffect(() => {
    const balancerDebug = props.playback_url_token?._balancer;
    if (balancerDebug) {
      console.log('[CDN balancer]', balancerDebug);
    }
  }, [props.playback_url_token]);

  const streamBlocked =
    !!props.is_stream && !!props.stream_requires_payment && !props.stream_entitled;

  const playbackUrlCandidates = [
    (props.stream ?? '').toString(),
    (props.sources?.[0]?.src ?? '').toString(),
  ].filter(Boolean);

  const isLikelyLiveStream = (() => {
    if (!playbackUrlCandidates.length) return false;
    // Wowza live suele verse como: https://host/<app>/live/playlist.m3u8
    return playbackUrlCandidates.some((url) => url.includes('/live'));
  })();

  const isLikelyVodStream = (() => {
    if (!playbackUrlCandidates.length) return false;
    // Wowza VOD común: /vod/mp4:dc/<file>.mp4/playlist.m3u8
    return playbackUrlCandidates.some((url) => url.includes('/vod/') || url.includes('mp4:'));
  })();

  const playerStates = {
    playerVolume: props.playerVolume ?? 1,
    playerSoundMuted: props.playerSoundMuted ?? false,
    videoQuality: props.videoQuality ?? 'Auto',
    videoPlaybackSpeed: props.videoPlaybackSpeed ?? 1,
    inTheaterMode: props.inTheaterMode ?? false,
  };

  const initPlayer = () => {
    if (streamBlocked) return;
    if (playerRef.current || props.errorMessage || !videoElemRef.current) return;

    if (!props.inEmbed) {
      window.removeEventListener('focus', initPlayer);
      document.removeEventListener('visibilitychange', initPlayer);
      videoElemRef.current.focus();
    }

    const subtitles = {
      on: false,
      languages: [],
    };

    if (props.subtitlesInfo?.length) {
      props.subtitlesInfo.forEach((sub) => {
        if (sub.src && sub.srclang && sub.label) {
          subtitles.languages.push({
            src: formatInnerLink(sub.src, props.siteUrl),
            srclang: sub.srclang,
            label: sub.label,
          });
        }
      });
      subtitles.on = subtitles.languages.length > 0;
    }

    let sources;
    const mediaIdSource = props.url.split('m=')[1];

    if (props.stream !== '') {
      const extractStreamKey = (url) => {
        try {
          const parsed = new URL(url);
          const pathParts = parsed.pathname.split('/').filter(Boolean);
          return pathParts[0] || null;
        } catch {
          return null;
        }
      };
    
      const streamKey = extractStreamKey(props.stream);
      const tokenEntry = props.playback_url_token?.[streamKey];
      const finalUrl = tokenEntry?.url
        ? tokenEntry.url
        : tokenEntry?.token
          ? `${props.stream}?${tokenEntry.token}`
          : props.stream;
    
      console.log("🎯 Stream key detectado:", streamKey);
      console.log("🔐 Token aplicado:", tokenEntry?.token);
      console.log("▶️ Final HLS URL:", finalUrl);
    
      sources = [
        {
          src: finalUrl,
          type: inferVideoSourceType(finalUrl)
        }
      ];
    } else {
      const vodFromServer = props.playback_url_token?.vod?.url;
      sources = vodFromServer
        ? [
            {
              src: vodFromServer,
              type: inferVideoSourceType(vodFromServer)
            }
          ]
        : []
    }

    const player = videojs(videoElemRef.current, {
      enabledTouchControls: true,
      controls: true,
      autoplay: true,
      muted : false,
      // Solo mostrar UI live cuando realmente parezca un stream live.
      // En Wowza VOD (HLS de MP4) video.js puede marcarlo como live (duration=Infinity)
      // y mostrar el botón LIVE; ahí lo neutralizamos con la limpieza defensiva.
      liveui: isLikelyLiveStream && !isLikelyVodStream,
      poster: props.poster,
      sources: sources,
      bigPlayButton: true,
      volume: playerStates.playerVolume,
      soundMuted: playerStates.playerSoundMuted,
      theaterMode: playerStates.inTheaterMode,
      videoPreviewThumb: props.previewSprite,
      controlBar: {
        theaterMode: props.hasTheaterMode,
        pictureInPictureToggle: false,
        next: props.hasNextLink,
        previous: props.hasPreviousLink,
        enableLowInitialPlaylist: false
      }
    });

    playerRef.current = player;
    props.onPlayerInitCallback?.(player);

    const isVodUrl = (url) => {
      const safeUrl = (url ?? '').toString();
      return safeUrl.includes('/vod/') || safeUrl.includes('mp4:');
    };

    const enforceNonLiveUi = () => {
      try {
        // Si explícitamente parece live, no tocar.
        if (isLikelyLiveStream && !isLikelyVodStream) return;

        const currentSrc = (player.currentSrc?.() ?? '').toString();
        const declaredSource = (sources?.[0]?.src ?? '').toString();
        const declaredStream = (props.stream ?? '').toString();
        const declaredPropSource = (props.sources?.[0]?.src ?? '').toString();

        const rootEl = player.el?.();
        const hasSeekToLiveDom = !!rootEl?.querySelector?.('.vjs-seek-to-live-control');

        // Tratamos como VOD si cualquiera lo indica o si video.js lo marcó como live
        // (caso típico Wowza VOD con duration=Infinity).
        const shouldNeutralizeLive =
          isLikelyVodStream ||
          isVodUrl(currentSrc) ||
          isVodUrl(declaredSource) ||
          isVodUrl(declaredStream) ||
          isVodUrl(declaredPropSource) ||
          player.hasClass?.('vjs-live') === true ||
          hasSeekToLiveDom;

        if (!shouldNeutralizeLive) return;

        player.removeClass('vjs-live');
        player.removeClass('vjs-liveui');

        const controlBar = player.getChild('controlBar');
        const liveDisplay =
          controlBar?.getChild?.('liveDisplay') ?? controlBar?.getChild?.('LiveDisplay');
        const seekToLive = controlBar?.getChild?.('seekToLive') ?? controlBar?.getChild?.('SeekToLive');

        liveDisplay?.hide?.();
        seekToLive?.hide?.();

        if (controlBar && seekToLive) {
          try {
            controlBar.removeChild(seekToLive);
            seekToLive.dispose?.();
          } catch (e) {
            // no-op
          }
        }

        if (rootEl?.querySelectorAll) {
          rootEl
            .querySelectorAll(
              '.vjs-seek-to-live-control, .vjs-live-control, .vjs-live-display'
            )
            .forEach((el) => {
              el.style.setProperty('display', 'none', 'important');
              el.style.setProperty('visibility', 'hidden', 'important');
              el.style.setProperty('pointer-events', 'none', 'important');
              el.setAttribute('aria-hidden', 'true');
            });
        }
      } catch (e) {
        // no-op
      }
    };

    enforceNonLiveUi();
    player.on('loadstart', enforceNonLiveUi);
    player.on('durationchange', enforceNonLiveUi);
    player.on('loadedmetadata', enforceNonLiveUi);
    player.on('ready', enforceNonLiveUi);

    // Reintentos cortos: a veces SeekToLive aparece después del init.
    try {
      vodUiTimeoutsRef.current.forEach((t) => clearTimeout(t));
      vodUiTimeoutsRef.current = [
        setTimeout(enforceNonLiveUi, 0),
        setTimeout(enforceNonLiveUi, 250),
        setTimeout(enforceNonLiveUi, 1000),
      ];
    } catch (e) {
      // no-op
    }

    try {
      vodUiObserverRef.current?.disconnect?.();
      const rootEl = player.el?.();
      if (rootEl && typeof MutationObserver !== 'undefined') {
        const observer = new MutationObserver(() => enforceNonLiveUi());
        observer.observe(rootEl, {
          subtree: true,
          childList: true,
          attributes: true,
          attributeFilter: ['class'],
        });
        vodUiObserverRef.current = observer;
      }
    } catch (e) {
      // no-op
    }

    player.qualityLevels();
    player.httpSourceSelector({
      default: 'auto'
    });

    if(props.hls_file !== ''){
      player.volume(0);
      player.muted(true);
    }

    if (subtitles.on) {
      subtitles.languages.forEach((track) => {
        player.addRemoteTextTrack(
          {
            kind: 'subtitles',
            src: track.src,
            srclang: track.srclang,
            label: track.label,
            default: false,
          },
          false
        );
      });
    }

  };
  

  const unsetPlayer = () => {
    if (vodUiTimeoutsRef.current?.length) {
      vodUiTimeoutsRef.current.forEach((t) => clearTimeout(t));
      vodUiTimeoutsRef.current = [];
    }
    if (vodUiObserverRef.current) {
      vodUiObserverRef.current.disconnect();
      vodUiObserverRef.current = null;
    }
    if (playerRef.current) {
      playerRef.current.dispose();
      playerRef.current = null;
    }
  };

  useEffect(() => {
    if (streamBlocked) {
      unsetPlayer();
      return;
    }
    if (!window.google?.ima) {
      const script = document.createElement('script');
      script.src = 'https://imasdk.googleapis.com/js/sdkloader/ima3.js';
      script.async = true;
      script.onload = () => {
        console.log('✅ Google IMA SDK cargado');
        initPlayer(); // Inicializa después de que el SDK esté listo
      };
      document.body.appendChild(script);
    } else {
      initPlayer();
    }
  
    return () => {
      unsetPlayer();
    };
  }, [streamBlocked]);

  if (streamBlocked) {
    return (
      <div className="video-player video-player-paywall">
        <div className="video-player-paywall-inner">
          <div className="video-player-paywall-title">Acceso restringido</div>
          <div className="video-player-paywall-subtitle">
            Debes comprar acceso para reproducir este stream.
          </div>
          {props.stream_checkout_url ? (
            <a
              className="video-player-paywall-button"
              href={props.stream_checkout_url}
            >
              Comprar acceso
            </a>
          ) : null}
        </div>
      </div>
    );
  }

  return props.errorMessage === null ? (
    <div className="video-player">
      <video
        ref={videoElemRef}
        id="content_video"
        className="video-js vjs-mediacms native-dimensions"
      ></video>
    </div>
  ) : (
    <VideoPlayerError errorMessage={props.errorMessage} />
  );
}

VideoPlayer.propTypes = {
  playerVolume: PropTypes.string,
  playerSoundMuted: PropTypes.bool,
  videoQuality: PropTypes.string,
  videoPlaybackSpeed: PropTypes.number,
  inTheaterMode: PropTypes.bool,
  siteId: PropTypes.string.isRequired,
  siteUrl: PropTypes.string.isRequired,
  errorMessage: PropTypes.string,
  cornerLayers: PropTypes.object,
  inEmbed: PropTypes.bool.isRequired,
  sources: PropTypes.array.isRequired,
  info: PropTypes.object.isRequired,
  enableAutoplay: PropTypes.bool.isRequired,
  hasTheaterMode: PropTypes.bool.isRequired,
  poster: PropTypes.string,
  adsTag : PropTypes.object,
  hls_file : PropTypes.string,
  previewSprite: PropTypes.object,
  onClickPreviousCallback: PropTypes.func,
  onClickNextCallback: PropTypes.func,
  onPlayerInitCallback: PropTypes.func,
  onStateUpdateCallback: PropTypes.func,
  onUnmountCallback: PropTypes.func,
  is_stream: PropTypes.bool,
  stream_requires_payment: PropTypes.bool,
  stream_entitled: PropTypes.bool,
  stream_checkout_url: PropTypes.string,
};

VideoPlayer.defaultProps = {
  errorMessage: null,
  cornerLayers: {},
};
