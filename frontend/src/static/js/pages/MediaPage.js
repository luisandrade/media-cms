import React from 'react';
import { SiteConsumer } from '../utils/contexts/';
import { MediaPageStore } from '../utils/stores/';
import AttachmentViewer from '../components/media-viewer/AttachmentViewer';
import AudioViewer from '../components/media-viewer/AudioViewer';
import ImageViewer from '../components/media-viewer/ImageViewer';
import PdfViewer from '../components/media-viewer/PdfViewer';
import VideoViewer from '../components/media-viewer/VideoViewer';
import { _VideoMediaPage } from './_VideoMediaPage';
import { formatInnerLink } from '../utils/helpers';
import {SiteContext} from '../utils/contexts/';

if (window.MediaCMS.site.devEnv) {
  const extractUrlParams = () => {
    let mediaId = null;
    let playlistId = null;

    const query = window.location.search.split('?')[1];

    if (query) {
      const params = query.split('&');
      params.forEach((param) => {
        if (0 === param.indexOf('m=')) {
          mediaId = param.split('m=')[1];
        } else if (0 === param.indexOf('pl=')) {
          playlistId = param.split('pl=')[1];
        }
      });
    }

    return { mediaId, playlistId };
  };

  const { mediaId, playlistId } = extractUrlParams();

  if (mediaId) {
    window.MediaCMS.mediaId = mediaId;
  }

  if (playlistId) {
    window.MediaCMS.playlistId = playlistId;
  }
}

export class MediaPage extends _VideoMediaPage {
  viewerContainerContent(mediaData) {

    const element = document.getElementById('page-media');
    let playbackUrls = {};
  
    if (element) {
      const rawData = element.getAttribute('data-playback-urls');

      console.log("raw data view normal",rawData);
      if (rawData) {
        try {
          playbackUrls = JSON.parse(rawData);
          console.log("🎥 Playback URLs (normal view):", playbackUrls);
        } catch (e) {
          console.error("❌ Error parsing playback_urls:", e);
        }
      }
    }

  

    switch (MediaPageStore.get('media-type')) {
      case 'video':
        return (
        <SiteConsumer>
          {(site) => (
            <VideoViewer
              data={{ ...mediaData, playback_urls: playbackUrls }}
              siteUrl={site.url}
              inEmbed={false}
            />
          )}
        </SiteConsumer>
        );
      case 'audio':
        return <AudioViewer />;
      case 'image':
        return <ImageViewer />;
      case 'pdf':
        const pdf_url = formatInnerLink(MediaPageStore.get('media-original-url'), SiteContext._currentValue.url);
        return <PdfViewer fileUrl={pdf_url} />;
    }

    return <AttachmentViewer />;
  }
}
