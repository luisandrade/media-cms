import React, { useEffect, useState } from 'react';
import { ApiUrlConsumer } from '../utils/contexts';
import { MediaListWrapper } from '../components/MediaListWrapper';
import { LazyLoadItemListAsync } from '../components/item-list/LazyLoadItemListAsync.jsx';
import { Page } from './Page';
import { translateString } from '../utils/helpers';
import { ManageAdsPage } from './ManageAdsPage';
import { ManageCategoryAdsPage } from './ManageCategoryAdsPage';
import './AdsTagsPage.scss';

interface AdsTagsPageProps {
  id?: string;
  title?: string;
}

type AdsManagementTab = 'ads' | 'categories';

function getActiveTabFromLocation(): AdsManagementTab {
  if ('undefined' === typeof window) {
    return 'ads';
  }

  const locationTab = new URLSearchParams(window.location.search).get('tab');
  return 'categories' === locationTab ? 'categories' : 'ads';
}

function persistActiveTab(tab: AdsManagementTab) {
  if ('undefined' === typeof window) {
    return;
  }

  const url = new URL(window.location.href);
  url.searchParams.set('tab', tab);
  window.history.replaceState({}, '', url.toString());
}

export const AdsTagsPage: React.FC<AdsTagsPageProps> = ({ id = 'adstag', title = translateString('Tags') }) => {
  const [activeTab, setActiveTab] = useState<AdsManagementTab>(() => getActiveTabFromLocation());

  useEffect(() => {
    const syncTabFromHistory = () => {
      setActiveTab(getActiveTabFromLocation());
    };

    window.addEventListener('popstate', syncTabFromHistory);
    return () => window.removeEventListener('popstate', syncTabFromHistory);
  }, []);

  const handleTabChange = (tab: AdsManagementTab) => {
    setActiveTab(tab);
    persistActiveTab(tab);
  };

  return (
    <Page id={id}>
      <ApiUrlConsumer>
        {(apiUrl) => (
          <MediaListWrapper title={title} className="items-list-ver">
            <LazyLoadItemListAsync singleLinkContent={true} inTagsList={true} requestUrl={apiUrl.archive.adstag} />
          </MediaListWrapper>
        )}
      </ApiUrlConsumer>

      {'ads' === activeTab ? (
        <ManageAdsPage activeTab={activeTab} onTabChange={handleTabChange} />
      ) : (
        <ManageCategoryAdsPage activeTab={activeTab} onTabChange={handleTabChange} />
      )}
    </Page>
  );
};
