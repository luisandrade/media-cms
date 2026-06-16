import React from 'react';
import { ApiUrlContext } from '../utils/contexts/';
import { csrfToken } from '../utils/helpers/';
import { MaterialIcon, SpinnerLoader } from '../components/_shared';
import { MediaListWrapper } from '../components/MediaListWrapper';
import { Page } from './_Page';
import './ManageWowzaPage.scss';

const WOWZA_APP_NAME_INVALID_RE = /[<>:'"\/\\|?*~]/;
const WOWZA_APP_NAME_INVALID_MESSAGE = 'no puede contener <, >, :, comillas, /, \\, |, ?, *, .. o ~.';

function validateWowzaName(value, label) {
  const normalized = (value || '').trim();

  if (!normalized) {
    return `${label} no puede estar vacío.`;
  }

  if (80 < normalized.length) {
    return `${label} no puede superar 80 caracteres.`;
  }

  if (WOWZA_APP_NAME_INVALID_RE.test(normalized) || -1 < normalized.indexOf('..')) {
    return `${label} ${WOWZA_APP_NAME_INVALID_MESSAGE}`;
  }

  return '';
}

function getErrorMessage(error) {
  if (error && error.message) {
    return error.message;
  }
  return 'No fue posible completar la operación.';
}

function connectionValue(app, field) {
  const streamName = app.stream_name || 'live';

  if ('rtmp_url' === field) {
    return app.rtmp_url || `rtmp://scl.edge.grupoz.cl/${app.name}`;
  }

  if ('stream_name' === field) {
    return streamName;
  }

  if ('publish_username' === field) {
    return app.publish_username || app.name;
  }

  if ('publish_password' === field) {
    return app.publish_password || '';
  }

  if ('hls_url' === field) {
    return app.hls_url || `https://scl.edge.grupoz.cl/${app.name}/${streamName}/playlist.m3u8`;
  }

  return '';
}

function withCacheBuster(url, cacheKey) {
  if (!cacheKey) {
    return url;
  }

  return `${url}${-1 === url.indexOf('?') ? '?' : '&'}refresh=${cacheKey}`;
}

function toDateTimeLocalInput(value) {
  if (!value) {
    return '';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }

  const pad = (number) => String(number).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatStreamCountdownDate(value) {
  if (!value) {
    return '';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }

  return date.toLocaleString([], {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export class ManageWowzaPage extends Page {
  constructor(props) {
    super(props, 'manage-wowza');

    this.state = {
      appName: '',
      scheduleId: '',
      isLoadingStatus: true,
      isLoadingApplications: true,
      isSubmitting: false,
      status: null,
      applications: [],
      applicationsCount: 0,
      maxApplications: 0,
      availableApplications: null,
      applicationsPage: 1,
      applicationsTotalPages: 1,
      result: null,
      activeAppName: '',
      deletingApplicationId: null,
      recordingApplicationId: null,
      connectionApplicationId: null,
      connectionSignalReady: false,
      connectionSignalRefreshKey: 0,
      copiedConnectionField: '',
      visiblePasswords: {},
      metadataApplicationId: null,
      metadataTitle: '',
      metadataCountdownAt: '',
      metadataPosterFile: null,
      metadataRemovePoster: false,
      savingMetadataApplicationId: null,
      error: null,
      validationError: '',
    };

    this.loadStatus = this.loadStatus.bind(this);
    this.loadApplications = this.loadApplications.bind(this);
    this.onInputChange = this.onInputChange.bind(this);
    this.onSubmit = this.onSubmit.bind(this);
    this.onDeleteApplication = this.onDeleteApplication.bind(this);
    this.onStartRecording = this.onStartRecording.bind(this);
    this.onShowConnection = this.onShowConnection.bind(this);
    this.onTogglePassword = this.onTogglePassword.bind(this);
    this.onCopyConnectionValue = this.onCopyConnectionValue.bind(this);
    this.onRefreshConnectionSignal = this.onRefreshConnectionSignal.bind(this);
    this.onConnectionSignalReady = this.onConnectionSignalReady.bind(this);
    this.onMetadataInputChange = this.onMetadataInputChange.bind(this);
    this.onMetadataFileChange = this.onMetadataFileChange.bind(this);
    this.onSaveMetadata = this.onSaveMetadata.bind(this);
  }

  componentDidMount() {
    this.loadStatus();
    this.loadApplications();
  }

  async loadStatus() {
    this.setState({ isLoadingStatus: true });

    try {
      const response = await fetch(ApiUrlContext._currentValue.manage.wowzaStatus, {
        credentials: 'same-origin',
      });
      const payload = await response.json();

      if (!response.ok || false === payload.success) {
        throw new Error(payload.message || 'Wowza no respondió correctamente.');
      }

      this.setState({
        status: payload.data,
        error: null,
        isLoadingStatus: false,
      });
    } catch (error) {
      this.setState({
        status: null,
        error: getErrorMessage(error),
        isLoadingStatus: false,
      });
    }
  }

  async loadApplications(page) {
    const nextPage = page || this.state.applicationsPage;
    this.setState({ isLoadingApplications: true });

    try {
      const response = await fetch(`${ApiUrlContext._currentValue.manage.wowzaApplications}?page=${nextPage}&page_size=10`, {
        credentials: 'same-origin',
      });
      const payload = await response.json();

      if (!response.ok || false === payload.success) {
        throw new Error(payload.message || 'No fue posible listar las aplicaciones creadas.');
      }

      this.setState({
        applications: payload.results || [],
        applicationsCount: payload.count || 0,
        maxApplications: payload.max_applications || 0,
        availableApplications: payload.available_applications,
        applicationsPage: payload.page || 1,
        applicationsTotalPages: payload.total_pages || 1,
        isLoadingApplications: false,
      });
    } catch (error) {
      this.setState({
        applications: [],
        applicationsCount: 0,
        maxApplications: 0,
        availableApplications: null,
        applicationsPage: 1,
        applicationsTotalPages: 1,
        error: getErrorMessage(error),
        isLoadingApplications: false,
      });
    }
  }

  onInputChange(ev) {
    this.setState({
      [ev.currentTarget.name]: ev.currentTarget.value,
      validationError: '',
      result: null,
      error: null,
    });
  }

  async onSubmit(ev) {
    ev.preventDefault();

    const appName = this.state.appName.trim();
    const scheduleId = this.state.scheduleId.trim() || appName;
    const appNameError = validateWowzaName(appName, 'El nombre de la aplicación');
    const scheduleIdError = validateWowzaName(scheduleId, 'El ID schedule');
    const isExistingApplication = this.state.applications.some((app) => app.name === appName);

    if (appNameError || scheduleIdError) {
      this.setState({
        validationError: appNameError || scheduleIdError,
      });
      return;
    }

    if (!isExistingApplication && this.state.maxApplications > 0 && this.state.availableApplications <= 0) {
      this.setState({
        validationError: `Ya llegaste al límite de ${this.state.maxApplications} aplicaciones disponibles en la plataforma.`,
      });
      return;
    }

    this.setState({
      isSubmitting: true,
      result: null,
      error: null,
      validationError: '',
    });

    try {
      const response = await fetch(ApiUrlContext._currentValue.manage.wowzaApplications, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken(),
        },
        body: JSON.stringify({
          name: appName,
          schedule_id: scheduleId,
        }),
      });
      const payload = await response.json();

      if (!response.ok || false === payload.success) {
        throw new Error(payload.message || 'Wowza rechazó la solicitud.');
      }

      this.setState({
        appName: '',
        scheduleId: '',
        result: payload,
        activeAppName: appName,
        error: null,
        isSubmitting: false,
      });
      this.loadStatus();
      this.loadApplications(1);
    } catch (error) {
      this.setState({
        error: getErrorMessage(error),
        result: null,
        isSubmitting: false,
      });
    }
  }

  async onDeleteApplication(app) {
    const confirmed = window.confirm(`¿Eliminar la aplicación ${app.name} de Wowza?`);

    if (!confirmed) {
      return;
    }

    this.setState({
      deletingApplicationId: app.id,
      error: null,
      result: null,
    });

    try {
      const response = await fetch(`${ApiUrlContext._currentValue.manage.wowzaApplications}/${app.id}`, {
        method: 'DELETE',
        credentials: 'same-origin',
        headers: {
          'X-CSRFToken': csrfToken(),
        },
      });
      const payload = await response.json();

      if (!response.ok || false === payload.success) {
        throw new Error(payload.message || 'No fue posible eliminar la aplicación.');
      }

      this.setState({
        deletingApplicationId: null,
      activeAppName: this.state.activeAppName === app.name ? '' : this.state.activeAppName,
      connectionApplicationId: this.state.connectionApplicationId === app.id ? null : this.state.connectionApplicationId,
      metadataApplicationId: this.state.metadataApplicationId === app.id ? null : this.state.metadataApplicationId,
      });
      this.loadApplications(this.state.applicationsPage);
      this.loadStatus();
    } catch (error) {
      this.setState({
        deletingApplicationId: null,
        error: getErrorMessage(error),
      });
    }
  }

  async onStartRecording(app) {
    const hasActiveRecorder = !!(app.is_recording || app.is_recording_waiting || app.is_recording_active);
    this.setState({
      recordingApplicationId: app.id,
      error: null,
      result: null,
    });

    try {
      const response = await fetch(`${ApiUrlContext._currentValue.manage.wowzaApplications}/${app.id}/recording`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken(),
        },
        body: JSON.stringify({
          action: hasActiveRecorder ? 'stop' : 'start',
        }),
      });
      const payload = await response.json();

      if (!response.ok || false === payload.success) {
        throw new Error(payload.message || `No fue posible ${hasActiveRecorder ? 'detener' : 'iniciar'} el recording.`);
      }

      this.setState({
        recordingApplicationId: null,
        result: payload,
        error: null,
      });
      this.loadApplications(this.state.applicationsPage);
    } catch (error) {
      this.setState({
        recordingApplicationId: null,
        error: getErrorMessage(error),
      });
    }
  }

  recordingButtonLabel(app) {
    if (this.state.recordingApplicationId === app.id) {
      return app.is_recording || app.is_recording_waiting || app.is_recording_active ? 'Deteniendo' : 'Iniciando';
    }

    if (app.is_recording) {
      return 'Grabando';
    }

    if (app.is_recording_waiting) {
      return 'Esperando señal';
    }

    return 'Iniciar recording';
  }

  recordingButtonIcon(app) {
    if (app.is_recording) {
      return 'stop_circle';
    }

    if (app.is_recording_waiting) {
      return 'schedule';
    }

    return 'fiber_manual_record';
  }

  onTogglePassword(appId) {
    this.setState((prevState) => ({
      visiblePasswords: {
        ...prevState.visiblePasswords,
        [appId]: !prevState.visiblePasswords[appId],
      },
    }));
  }

  onShowConnection(app) {
    this.setState({
      connectionApplicationId: app.id,
      metadataApplicationId: app.id,
      metadataTitle: app.stream_title || '',
      metadataCountdownAt: toDateTimeLocalInput(app.countdown_at),
      metadataPosterFile: null,
      metadataRemovePoster: false,
      connectionSignalReady: false,
      connectionSignalRefreshKey: Date.now(),
      copiedConnectionField: '',
      visiblePasswords: {
        ...this.state.visiblePasswords,
        [app.id]: true,
      },
    });
  }

  onCopyConnectionValue(app, field) {
    const value = connectionValue(app, field);

    if (!value) {
      return;
    }

    const markCopied = () => {
      this.setState({ copiedConnectionField: `${app.id}-${field}` });
      window.setTimeout(() => {
        if (this.state.copiedConnectionField === `${app.id}-${field}`) {
          this.setState({ copiedConnectionField: '' });
        }
      }, 1800);
    };

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(markCopied).catch(markCopied);
      return;
    }

    const textarea = document.createElement('textarea');
    textarea.value = value;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.top = '-1000px';
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
    markCopied();
  }

  onRefreshConnectionSignal() {
    this.setState({
      connectionSignalReady: false,
      connectionSignalRefreshKey: Date.now(),
    });
  }

  onConnectionSignalReady() {
    if (!this.state.connectionSignalReady) {
      this.setState({ connectionSignalReady: true });
    }
  }

  onMetadataInputChange(ev) {
    const { name, value, checked, type } = ev.currentTarget;
    this.setState({
      [name]: type === 'checkbox' ? checked : value,
      error: null,
      result: null,
    });
  }

  onMetadataFileChange(ev) {
    this.setState({
      metadataPosterFile: ev.currentTarget.files && ev.currentTarget.files[0] ? ev.currentTarget.files[0] : null,
      metadataRemovePoster: false,
      error: null,
      result: null,
    });
  }

  async onSaveMetadata(ev) {
    ev.preventDefault();

    const appId = this.state.metadataApplicationId;
    if (!appId) {
      return;
    }

    const formData = new FormData();
    formData.append('stream_title', this.state.metadataTitle);
    formData.append('countdown_at', this.state.metadataCountdownAt);
    if (this.state.metadataPosterFile) {
      formData.append('poster_image', this.state.metadataPosterFile);
    }
    if (this.state.metadataRemovePoster) {
      formData.append('remove_poster', '1');
    }

    this.setState({
      savingMetadataApplicationId: appId,
      error: null,
      result: null,
    });

    try {
      const response = await fetch(`${ApiUrlContext._currentValue.manage.wowzaApplications}/${appId}`, {
        method: 'PATCH',
        credentials: 'same-origin',
        headers: {
          'X-CSRFToken': csrfToken(),
        },
        body: formData,
      });
      const payload = await response.json();

      if (!response.ok || false === payload.success) {
        throw new Error(payload.message || 'No fue posible guardar los datos del stream.');
      }

      const updatedApp = payload.wowza_application;
      this.setState({
        applications: this.state.applications.map((app) => (app.id === appId ? { ...app, ...updatedApp } : app)),
        savingMetadataApplicationId: null,
        metadataPosterFile: null,
        metadataRemovePoster: false,
        result: payload,
        error: null,
      });
    } catch (error) {
      this.setState({
        savingMetadataApplicationId: null,
        error: getErrorMessage(error),
      });
    }
  }

  renderConnectionField(app, field, label, icon, hint) {
    const value = connectionValue(app, field);
    const copied = this.state.copiedConnectionField === `${app.id}-${field}`;

    return (
      <div className="manage-wowza-connection-card">
        <div className="manage-wowza-connection-card-head">
          <span className="manage-wowza-connection-card-icon">
            <MaterialIcon type={icon} />
          </span>
          <strong>{label}</strong>
        </div>
        <div className="manage-wowza-connection-value">
          <input value={value} readOnly />
          <button type="button" onClick={() => this.onCopyConnectionValue(app, field)} title={`Copiar ${label}`}>
            <MaterialIcon type={copied ? 'check' : 'content_copy'} />
            <span>{copied ? 'Copiado' : 'Copiar'}</span>
          </button>
        </div>
        {hint ? <div className="manage-wowza-connection-hint">{hint}</div> : null}
      </div>
    );
  }

  renderConnectionPanel(app) {
    if (!app) {
      return null;
    }

    const hlsUrl = withCacheBuster(connectionValue(app, 'hls_url'), this.state.connectionSignalRefreshKey);

    return (
      <section className="manage-wowza-connection">
        <div className="manage-wowza-connection-head">
          <div>
            <h2>Conexión de {app.name}</h2>
            <span>Señal de monitoreo y credenciales para configurar Wirecast u otro encoder RTMP.</span>
          </div>
          <div className="manage-wowza-connection-head-actions">
            <button type="button" onClick={this.onRefreshConnectionSignal} title="Refrescar señal">
              <MaterialIcon type="refresh" />
            </button>
            <button type="button" onClick={() => this.setState({ connectionApplicationId: null, metadataApplicationId: null })} title="Cerrar conexión">
              <MaterialIcon type="close" />
            </button>
          </div>
        </div>

        <div className="manage-wowza-signal">
          <video
            key={`${app.id}-${this.state.connectionSignalRefreshKey}`}
            controls
            playsInline
            src={hlsUrl}
            onLoadedData={this.onConnectionSignalReady}
            onCanPlay={this.onConnectionSignalReady}
            onPlaying={this.onConnectionSignalReady}
          />
          <div
            className={`manage-wowza-signal-placeholder ${app.poster_image_url ? 'manage-wowza-signal-placeholder-poster' : ''} ${
              this.state.connectionSignalReady ? 'manage-wowza-signal-placeholder-hidden' : ''
            }`}
            style={
              app.poster_image_url
                ? {
                    backgroundImage: `linear-gradient(180deg, rgba(5, 6, 10, 0.24), rgba(5, 6, 10, 0.72)), url("${app.poster_image_url}")`,
                  }
                : null
            }
          >
            <span className="manage-wowza-live-icon">
              <MaterialIcon type="radio_button_checked" />
            </span>
            <strong>Esperando señal de streaming...</strong>
            <span>Configura tu software de streaming con los datos de conexión de abajo</span>
          </div>
        </div>

        <div className="manage-wowza-connection-grid">
          {this.renderConnectionField(app, 'rtmp_url', 'RTMP', 'link', 'Usa esta URL en OBS Studio, Streamlabs o cualquier software compatible con RTMP.')}
          {this.renderConnectionField(app, 'stream_name', 'Stream', 'vpn_key')}
          {this.renderConnectionField(app, 'publish_username', 'Usuario', 'person')}
          {this.renderConnectionField(app, 'publish_password', 'Password', 'lock', (
            <React.Fragment>
              Esta clave es única para tu cuenta. <strong>No la compartas</strong> o cualquiera podrá transmitir en tu canal.
            </React.Fragment>
          ))}
        </div>
      </section>
    );
  }

  renderMetadataPanel(app) {
    if (!app) {
      return null;
    }

    const isSaving = this.state.savingMetadataApplicationId === app.id;

    return (
      <section className="manage-wowza-metadata">
        <div className="manage-wowza-connection-head">
          <div>
            <h2>Datos públicos de {app.name}</h2>
            <span>Título, portada y fecha para la cuenta regresiva de esta señal.</span>
          </div>
          <div className="manage-wowza-connection-head-actions">
            <button type="button" onClick={() => this.setState({ metadataApplicationId: null })} title="Cerrar edición">
              <MaterialIcon type="close" />
            </button>
          </div>
        </div>

        <form className="manage-wowza-metadata-form" onSubmit={this.onSaveMetadata}>
          <div className="manage-wowza-metadata-grid">
            <label>
              Título del stream
              <input
                name="metadataTitle"
                value={this.state.metadataTitle}
                onChange={this.onMetadataInputChange}
                maxLength="160"
                placeholder={app.name}
              />
            </label>

            <label>
              Fecha de cuenta regresiva
              <input
                name="metadataCountdownAt"
                type="datetime-local"
                value={this.state.metadataCountdownAt}
                onChange={this.onMetadataInputChange}
              />
            </label>

            <label>
              Imagen de portada
              <input type="file" accept="image/*" onChange={this.onMetadataFileChange} />
            </label>

            <label className="manage-wowza-metadata-check">
              <input
                name="metadataRemovePoster"
                type="checkbox"
                checked={this.state.metadataRemovePoster}
                onChange={this.onMetadataInputChange}
                disabled={!app.poster_image_url}
              />
              Quitar imagen actual
            </label>
          </div>

          {app.poster_image_url ? (
            <div className="manage-wowza-metadata-poster">
              <img src={app.poster_image_url} alt={`Portada de ${app.name}`} />
              <span>Imagen actual</span>
            </div>
          ) : null}

          <button className="manage-wowza-submit manage-wowza-metadata-submit" type="submit" disabled={isSaving}>
            {isSaving ? <SpinnerLoader size="tiny" /> : <MaterialIcon type="save" />}
            <span>{isSaving ? 'Guardando' : 'Guardar datos del stream'}</span>
          </button>
        </form>
      </section>
    );
  }

  pageContent() {
    const {
      appName,
      scheduleId,
      isLoadingStatus,
      isLoadingApplications,
      isSubmitting,
      status,
      applications,
      applicationsCount,
      maxApplications,
      availableApplications,
      applicationsPage,
      applicationsTotalPages,
      result,
      activeAppName,
      deletingApplicationId,
      recordingApplicationId,
      connectionApplicationId,
      metadataApplicationId,
      visiblePasswords,
      error,
      validationError,
    } = this.state;
    const previewAppName = appName.trim() || 'nombre_app';
    const previewScheduleId = scheduleId.trim() || previewAppName;
    const connectionApplication = applications.find((app) => app.id === connectionApplicationId);
    const metadataApplication = applications.find((app) => app.id === metadataApplicationId);
    const currentAppName = appName.trim();
    const isExistingApplication = applications.some((app) => app.name === currentAppName);
    const hasApplicationLimit = maxApplications > 0;
    const hasReachedApplicationLimit = hasApplicationLimit && availableApplications <= 0;
    const canSubmitApplication = status && (!hasReachedApplicationLimit || isExistingApplication);
    const quotaText = hasApplicationLimit
      ? `${applicationsCount} de ${maxApplications} aplicaciones creadas`
      : `${applicationsCount} aplicaciones creadas`;
    const availabilityText = hasApplicationLimit
      ? hasReachedApplicationLimit
        ? 'Límite alcanzado'
        : `${availableApplications} disponibles`
      : 'Sin límite configurado';

    return (
      <MediaListWrapper className="items-list-hor manage-wowza-wrapper">
        <div className="manage-wowza-page">
          <div className="manage-wowza-head">
            <div>
              <h1>Control de señales</h1>
              <p>Crear aplicaciones live y aplicar módulos operativos de Stream Publisher y Push Publish.</p>
            </div>
            <button className="manage-wowza-refresh" onClick={this.loadStatus} disabled={isLoadingStatus}>
              <MaterialIcon type="refresh" />
              <span>Actualizar estado</span>
            </button>
          </div>

          <div className={`manage-wowza-status ${status ? 'manage-wowza-status-available' : 'manage-wowza-status-unavailable'}`}>
            <div className="manage-wowza-status-icon">
              {isLoadingStatus ? <SpinnerLoader size="small" /> : <MaterialIcon type={status ? 'check_circle' : 'error'} />}
            </div>
            <div>
              <strong>{status ? 'Wowza API disponible' : isLoadingStatus ? 'Consultando Wowza' : 'Wowza API no disponible'}</strong>
              <span>
                {status
                  ? 'El panel puede crear aplicaciones en el servidor configurado.'
                  : isLoadingStatus
                  ? 'Validando conectividad con el API Manager.'
                  : 'Revisa conectividad, credenciales o permisos del API Manager.'}
              </span>
            </div>
          </div>

          <div className="manage-wowza-layout">
            <form className="manage-wowza-form" onSubmit={this.onSubmit}>
              <div className="manage-wowza-form-head">
                <MaterialIcon type="settings_input_antenna" />
                <h2>Nueva aplicación live</h2>
              </div>

              <label>
                Nombre de aplicación
                <input
                  name="appName"
                  value={appName}
                  onChange={this.onInputChange}
                  placeholder="eventoz06"
                  autoComplete="off"
                />
              </label>

              <label>
                ID schedule
                <input
                  name="scheduleId"
                  value={scheduleId}
                  onChange={this.onInputChange}
                  placeholder={previewAppName}
                  autoComplete="off"
                />
              </label>

              <button
                className="manage-wowza-submit"
                type="submit"
                disabled={isSubmitting || !canSubmitApplication}
                title={!status ? 'Wowza API no disponible' : hasReachedApplicationLimit && !isExistingApplication ? 'Límite de aplicaciones alcanzado' : ''}
              >
                {isSubmitting ? <SpinnerLoader size="tiny" /> : <MaterialIcon type="add_circle" />}
                <span>{isSubmitting ? 'Creando aplicación' : 'Crear aplicación'}</span>
              </button>
            </form>

            <section className="manage-wowza-preview">
              <div className="manage-wowza-preview-head">
                <MaterialIcon type="rule" />
                <h2>Configuración aplicada</h2>
              </div>
              <dl>
                <dt>Tipo</dt>
                <dd>Live</dd>
                <dt>Stream type</dt>
                <dd>live-record</dd>
                <dt>HLS packetizer</dt>
                <dd>cupertinostreamingpacketizer</dd>
                <dt>HTTP streamer</dt>
                <dd>cupertinostreaming</dd>
                <dt>Schedule</dt>
                <dd>{`streamschedule-${previewScheduleId}.smil`}</dd>
                <dt>Módulos</dt>
                <dd>Core, Logging, FLVPlayback, StreamPublisher, PushPublish</dd>
              </dl>
            </section>
          </div>

          {validationError || error || result ? (
            <div className="manage-wowza-feedback">
              {validationError ? <div className="manage-wowza-message manage-wowza-message-error">{validationError}</div> : null}
              {error ? <div className="manage-wowza-message manage-wowza-message-error">{error}</div> : null}
              {result ? <div className="manage-wowza-message manage-wowza-message-success">{result.message || 'Operación completada correctamente.'}</div> : null}
            </div>
          ) : null}

          <section className="manage-wowza-apps">
            <div className="manage-wowza-apps-head">
              <div>
                <h2>Aplicaciones creadas en la plataforma</h2>
                <span>{applicationsCount ? `${quotaText} (${availabilityText})` : `Sin aplicaciones guardadas (${availabilityText})`}</span>
              </div>
              {activeAppName ? <strong>Última creada: {activeAppName}</strong> : null}
            </div>

            {isLoadingApplications ? (
              <div className="manage-wowza-apps-empty">
                <SpinnerLoader size="small" />
                <span>Cargando aplicaciones</span>
              </div>
            ) : applications.length ? (
              <React.Fragment>
                <div className="manage-wowza-apps-list">
                  <div className="manage-wowza-app-row manage-wowza-app-row-head">
                    <span>Aplicación</span>
                    <span>Recording</span>
                    <span>Usuario</span>
                    <span>Password</span>
                    <span>Estado</span>
                    <span>Acciones</span>
                  </div>
                  {applications.map((app) => (
                    <div className={`manage-wowza-app-row ${connectionApplicationId === app.id || activeAppName === app.name ? 'manage-wowza-app-row-active' : ''}`} key={app.id || app.name}>
                      <span>
                        <MaterialIcon type={connectionApplicationId === app.id || activeAppName === app.name ? 'radio_button_checked' : 'radio_button_unchecked'} />
                        <span className="manage-wowza-app-name">
                          <strong>{app.stream_title || app.name}</strong>
                          <small>{app.name}</small>
                          {app.countdown_at ? <em>{formatStreamCountdownDate(app.countdown_at)}</em> : null}
                        </span>
                      </span>
                      <span>
                        <button
                          className={`manage-wowza-record ${app.is_recording ? 'manage-wowza-record-active' : ''} ${
                            app.is_recording_waiting ? 'manage-wowza-record-waiting' : ''
                          }`}
                          type="button"
                          onClick={() => this.onStartRecording(app)}
                          disabled={recordingApplicationId === app.id}
                          title={
                            app.is_recording || app.is_recording_waiting || app.is_recording_active
                              ? 'Detener recording'
                              : 'Iniciar recording segmentado por duración'
                          }
                        >
                          {recordingApplicationId === app.id ? (
                            <SpinnerLoader size="small" />
                          ) : (
                            <MaterialIcon type={this.recordingButtonIcon(app)} />
                          )}
                          <span>{this.recordingButtonLabel(app)}</span>
                        </button>
                      </span>
                      <span>{app.publish_username || app.name}</span>
                      <span>
                        <span className="manage-wowza-secret">
                          <span>{visiblePasswords[app.id] ? app.publish_password : '************'}</span>
                          <button type="button" onClick={() => this.onTogglePassword(app.id)} title={visiblePasswords[app.id] ? 'Ocultar password' : 'Ver password'}>
                            <MaterialIcon type={visiblePasswords[app.id] ? 'visibility_off' : 'visibility'} />
                          </button>
                        </span>
                      </span>
                      <span>
                        <span className={`manage-wowza-live-state ${app.is_live ? 'manage-wowza-live-state-on' : 'manage-wowza-live-state-off'}`}>
                          <span />
                          {app.is_live ? 'En vivo' : 'Offline'}
                        </span>
                      </span>
                      <span>
                        <span className="manage-wowza-row-actions">
                          <button className="manage-wowza-connect" type="button" onClick={() => this.onShowConnection(app)} title="Ver conexión">
                            <MaterialIcon type="settings_input_hdmi" />
                            <span>Conexión</span>
                          </button>
                          <button
                            className="manage-wowza-delete"
                            type="button"
                            onClick={() => this.onDeleteApplication(app)}
                            disabled={deletingApplicationId === app.id}
                            title="Eliminar aplicación"
                          >
                            {deletingApplicationId === app.id ? <SpinnerLoader size="small" /> : <MaterialIcon type="delete" />}
                            <span>{deletingApplicationId === app.id ? 'Eliminando' : 'Eliminar'}</span>
                          </button>
                        </span>
                      </span>
                    </div>
                  ))}
                </div>
                <div className="manage-wowza-pagination">
                  <button type="button" onClick={() => this.loadApplications(applicationsPage - 1)} disabled={applicationsPage <= 1}>
                    <MaterialIcon type="chevron_left" />
                    <span>Anterior</span>
                  </button>
                  <strong>
                    Página {applicationsPage} de {applicationsTotalPages}
                  </strong>
                  <button type="button" onClick={() => this.loadApplications(applicationsPage + 1)} disabled={applicationsPage >= applicationsTotalPages}>
                    <span>Siguiente</span>
                    <MaterialIcon type="chevron_right" />
                  </button>
                </div>
              </React.Fragment>
            ) : (
              <div className="manage-wowza-apps-empty">
                <MaterialIcon type="info" />
                <span>Crea una aplicación para verla en este listado.</span>
              </div>
            )}
          </section>

          {this.renderConnectionPanel(connectionApplication)}
          {this.renderMetadataPanel(metadataApplication)}

          {result ? (
            <section className="manage-wowza-result">
              <h2>Respuesta Wowza</h2>
              <pre>{JSON.stringify(result, null, 2)}</pre>
            </section>
          ) : null}
        </div>
      </MediaListWrapper>
    );
  }
}
