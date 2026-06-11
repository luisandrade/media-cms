import React from 'react';
import { LinksContext } from '../../utils/contexts/';
import { PageStore } from '../../utils/stores/';
import { MediaItemAudio as AudioItem } from './MediaItemAudio';
import { MediaItemVideo as VideoItem } from './MediaItemVideo';
import { MediaItem as ImageItem } from './MediaItem';
import { MediaItem as PdfItem } from './MediaItem';
import { MediaItem as AttachmentItem } from './MediaItem';
import { PlaylistItem } from './PlaylistItem';
import { TaxonomyItem } from './TaxonomyItem';
import { UserItem } from './UserItem';

function extractPlaylistId() {
  let playlistId = null;

  const getParamsString = window.location.search;

  if ('' !== getParamsString) {
    let tmp = getParamsString.split('?');

    if (2 === tmp.length) {
      tmp = tmp[1].split('&');

      let x;

      let i = 0;
      while (i < tmp.length) {
        x = tmp[i].split('=');

        if ('pl' === x[0]) {
          if (2 === x.length) {
            playlistId = x[1];
          }

          break;
        }

        i += 1;
      }
    }
  }

  return playlistId;
}

function itemPageLink(props, item) {
  if (props.inCategoriesList) {
    return LinksContext._currentValue.search.category + item.title.replace(' ', '%20');
  }

  if (props.inTagsList) {
    return LinksContext._currentValue.search.tag + item.title.replace(' ', '%20');
  }

  const playlistId = extractPlaylistId();

  if (props.inPlaylistView && playlistId) {
    return item.url + '&pl=' + playlistId;
  }

  if (void 0 !== props.playlistId && null !== props.playlistId) {
    return item.url + '&pl=' + props.playlistId;
  }

  return item.url;
}

function livePreviewTitle(value) {
  const normalized = (value || 'Señal en vivo').trim();
  return normalized || 'Señal en vivo';
}

function livePreviewInitials(title) {
  const words = livePreviewTitle(title).replace(/[_-]+/g, ' ').split(/\s+/).filter(Boolean);
  const initials = words.slice(0, 2).map((word) => word.charAt(0).toUpperCase()).join('');
  return initials || 'LV';
}

function livePreviewColor(title) {
  const colors = ['#ff121f', '#2f9d55', '#0f7fd8', '#7c4dff', '#f59f00'];
  const normalized = livePreviewTitle(title);
  let hash = 0;

  for (let i = 0; i < normalized.length; i += 1) {
    hash = (hash + normalized.charCodeAt(i) * (i + 1)) % colors.length;
  }

  return colors[hash];
}

function escapeSvgText(value) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function truncateLivePreviewTitle(title) {
  return 34 < title.length ? `${title.slice(0, 31)}...` : title;
}

function livePreviewDataUrl(title, isLiveOnline) {
  const safeTitle = escapeSvgText(truncateLivePreviewTitle(livePreviewTitle(title)));
  const initials = escapeSvgText(livePreviewInitials(title));
  const accent = isLiveOnline ? livePreviewColor(title) : '#6b7280';
  const statusText = isLiveOnline ? 'EN VIVO' : 'OFFLINE';
  const footerText = isLiveOnline ? 'Streaming' : 'Sin señal';
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#10131d"/>
<stop offset="0.58" stop-color="#242936"/>
<stop offset="1" stop-color="#111111"/>
</linearGradient>
</defs>
<rect width="640" height="360" fill="url(#bg)"/>
<circle cx="514" cy="88" r="96" fill="${accent}" opacity="0.18"/>
<circle cx="114" cy="292" r="110" fill="#ffffff" opacity="0.06"/>
<rect x="34" y="30" width="132" height="38" rx="5" fill="${accent}"/>
<circle cx="58" cy="49" r="7" fill="#ffffff"/>
<text x="76" y="55" font-family="Arial, Helvetica, sans-serif" font-size="18" font-weight="700" fill="#ffffff">${statusText}</text>
<text x="320" y="186" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="86" font-weight="800" fill="#ffffff">${initials}</text>
<text x="320" y="245" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="30" font-weight="700" fill="#ffffff">${safeTitle}</text>
<text x="320" y="282" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="17" font-weight="700" fill="${accent}">${footerText}</text>
</svg>`;

  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}

export function listItemProps(props, item, index) {
  const isArchiveItem = props.inCategoriesList || props.inTagsList;
  const isUserItem = !isArchiveItem && void 0 !== item.username;
  const isPlaylistItem =
    !isArchiveItem &&
    !isUserItem &&
    ('playlist' === item.media_type || (void 0 !== item.url && -1 < item.url.indexOf('playlists'))); // TODO: Improve this.
  const isMediaItem = !isArchiveItem && !isUserItem && !isPlaylistItem;
  const isSearchItem = 'search-results' === PageStore.get('current-page'); // TODO: Improve this.

  const url = {
    view: itemPageLink(props, item),
    edit: props.canEdit ? item.url.replace('view?m=', 'edit?m=') : null,
  };

  if (window.MediaCMS.site.devEnv && -1 < url.view.indexOf('view?')) {
    url.view = '/media.html?' + url.view.split('view?')[1];
  }

  let type, title, date, description, meta_description;

  title =
    void 0 !== item.username && 'string' === typeof item.username
      ? item.username
      : void 0 !== item.title && 'string' === typeof item.title
      ? item.title
      : null;

  const isLiveStream = 'boolean' === typeof item.is_live || !!(item.stream && item.stream !== '');
  const isLiveOnline = true === item.is_live;
  const generatedLivePreview = isLiveStream ? livePreviewDataUrl(title || item.name || item.stream, isLiveOnline) : '';
  const thumbnail = isLiveStream ? item.thumbnail_url || generatedLivePreview : item.thumbnail_url || '';
  const previewThumbnail = isLiveStream ? item.preview_url || generatedLivePreview : item.preview_url || '';

  date =
    void 0 !== item.date_added && 'string' === typeof item.date_added
      ? item.date_added
      : void 0 !== item.add_date && 'string' === typeof item.add_date
      ? item.add_date
      : null;

  // description = props.preferSummary && 'string' === typeof props.summary ? props.summary.trim() : ( 'string' === typeof item.description ? item.description.trim() : null );
  // description = null === description ? description : description.replace(/(<([^>]+)>)/ig,"");

  if (isUserItem) {
    type = 'user';
  } else if (isPlaylistItem) {
    type = 'playlist';
  } else if (isMediaItem) {
    type = item.media_type;
  }

  const taxonomyPage = {
    current: false,
    type: null,
  };

  const playlistPage = {
    current: props.inPlaylistPage,
    id: props.playlistId,
    hideOptions: props.hidePlaylistOptions || false,
    hideOrderNumber: props.hidePlaylistOrderNumber || false,
  };

  const playlistPlayback = {
    current: props.inPlaylistView,
    id: props.playlistId,
    activeItem: props.playlistActiveItem || false,
    hideOrderNumber: props.hidePlaylistOrderNumber || false,
  };

  if (isArchiveItem) {
    if (props.inCategoriesList) {
      taxonomyPage.type = 'categories';
    } else if (props.inTagsList) {
      taxonomyPage.type = 'tags';
    }

    if (null !== taxonomyPage.type) {
      taxonomyPage.current = true;
    }
  }

  const author = {
    name: item.author_name || item.user,
    url: item.author_profile ? item.author_profile.replace(' ', '%20') : null,
  };

  const stats = {
    views: item.views || null,
  };

  const hide = {
    allMeta: props.hideAllMeta || false,
  };

  let args = {
    order: index + 1,
    type,
    title,
    date,
    url,
    author,
    stats,
    thumbnail,
    taxonomyPage,
    playlistPage,
    playlistPlayback,
    canEdit: null !== url.edit,
    singleLinkContent: props.singleLinkContent || false,
    hasMediaViewer: 0 === index && 'video' === item.media_type && !!props.firstItemViewer,
    hasMediaViewerDescr: false,
    isLiveStream,
    isLiveOnline,
  };

  args.hasMediaViewerDescr = args.hasMediaViewer && !!props.firstItemDescr;

  if (!args.hasMediaViewerDescr) {
    description =
      props.preferSummary && 'string' === typeof props.summary
        ? props.summary.trim()
        : 'string' === typeof item.description
        ? item.description.trim()
        : null;
    description = null === description ? description : description.replace(/(<([^>]+)>)/gi, '');

    if (isSearchItem || props.inCategoriesList || 'user' === type) {
      args.description = description;
    } else {
      args.meta_description = description;
    }
  } else {
    if (!!props.firstItemViewer) {
      description = 'string' === typeof props.summary ? props.summary.trim() : null;
    } else {
      description = 'string' === typeof item.description ? item.description.trim() : null;
    }

    description = null === description ? description : description.replace(/(<([^>]+)>)/gi, '');

    args.description = description;

    // TODO: Improve this.
    if (props.summary) {
      meta_description = props.summary.trim();
      meta_description = null === meta_description ? meta_description : meta_description.replace(/(<([^>]+)>)/gi, '');
      args.meta_description = meta_description;
    }
  }

  if ('video' === type) {
    args.previewThumbnail = previewThumbnail;
    args.isLiveStream = isLiveStream;
    args.isLiveOnline = isLiveOnline;
  }

  if ('video' === type || 'audio' === type) {
    args.duration = item.duration;
  }

  if ((isArchiveItem || isPlaylistItem) && !isNaN(item.media_count)) {
    args.media_count = parseInt(item.media_count, 10);
  }

  if (isMediaItem) {
    hide.date = props.hideDate || false;
    hide.views = props.hideViews || false;
    hide.author = props.hideAuthor || false;
  }

  args = { ...args, hide };

  return args;
}

export function ListItem(props) {
  let isMediaItem = false;

  const args = {
    order: props.order,
    title: props.title,
    link: props.url.view,
    thumbnail: props.thumbnail,
    publish_date: props.date,
    singleLinkContent: props.singleLinkContent,
    hasMediaViewer: props.hasMediaViewer,
    hasMediaViewerDescr: props.hasMediaViewerDescr,
  };

  switch (props.type) {
    case 'user':
      break;
    case 'playlist':
      break;
    case 'video':
      isMediaItem = true;
      args.duration = props.duration;
      args.preview_thumbnail = props.previewThumbnail;
      break;
    case 'audio':
      isMediaItem = true;
      args.duration = props.duration;
      break;
    case 'image':
      isMediaItem = true;
      break;
    case 'pdf':
      isMediaItem = true;
      break;
  }

  if (void 0 !== props.description) {
    args.description = props.description;
  }

  if (void 0 !== props.meta_description) {
    args.meta_description = props.meta_description;
  }

  if ((props.taxonomyPage.current || 'playlist' === props.type) && !isNaN(props.media_count)) {
    args.media_count = props.media_count;
  }

  args.hideAllMeta = props.hide.allMeta;

  if (isMediaItem) {
    args.views = props.stats.views;

    args.author_name = props.author.name;
    args.author_link = props.author.url;

    args.hideDate = props.hide.date;
    args.hideViews = props.hide.views;
    args.hideAuthor = props.hide.author;
  }

  if (props.playlistPage.current || props.playlistPlayback.current) {
    args.playlistOrder = props.order;

    if (props.playlistPlayback.current) {
      args.playlist_id = props.playlistPlayback.id;
      args.playlistActiveItem = props.playlistPlayback.activeItem;
      args.hidePlaylistOrderNumber = props.playlistPlayback.hideOrderNumber;
    } else {
      args.playlist_id = props.playlistPage.id;
      args.hidePlaylistOptions = props.playlistPage.hideOptions;
      args.hidePlaylistOrderNumber = props.playlistPage.hideOrderNumber;
    }
  }

  if (props.canEdit) {
    args.editLink = props.url.edit;
  }

  if (props.taxonomyPage.current) {
    switch (props.taxonomyPage.type) {
      case 'categories':
        return <TaxonomyItem {...args} type="category" />;
      case 'tags':
        return <TaxonomyItem {...args} type="tag" />;
    }
  }

  switch (props.type) {
    case 'user':
      return <UserItem {...args} />;
    case 'playlist':
      if (window.MediaCMS.site.devEnv) {
        args.link = args.link.replace('/playlists/', 'playlist.html?pl=');
      }
      return <PlaylistItem {...args} />;
    case 'video':
      return <VideoItem {...args} />;
    case 'audio':
      return <AudioItem {...args} />;
    case 'image':
      return <ImageItem {...args} type="image" />;
    case 'pdf':
      return <PdfItem {...args} type="pdf" />;
  }

  return <AttachmentItem {...args} type="attachment" />;
}
