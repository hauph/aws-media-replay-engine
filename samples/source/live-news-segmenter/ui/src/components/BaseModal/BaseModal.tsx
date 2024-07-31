import { faXmark } from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { FC, ReactNode } from 'react';

import { Content, Footer, Header, Modal } from './style';

import { BaseFunction } from '@src/types';

interface BaseModalProps {
  visible: boolean;
  onClose: BaseFunction;
  width?: number;
  height?: number;
  className?: string;
  content: ReactNode;
  header: string;
  footer: ReactNode;
}

export const BaseModal: FC<BaseModalProps> = ({
  visible,
  onClose,
  width,
  height,
  className,
  content,
  header,
  footer,
}) => {
  return (
    <Modal
      visible={visible}
      onClose={onClose}
      width={width ?? 400}
      height={height}
      className={className}
      customStyles={height === undefined ? { height: 'auto' } : {}}
    >
      <Header alignItems="center" justifyContent="space-between">
        <span className="header-title">{header}</span>
        <FontAwesomeIcon
          icon={faXmark}
          className="header-btn-close"
          onClick={onClose}
        />
      </Header>
      <Content>{content}</Content>
      <Footer justifyContent="end" height={28}>
        {footer}
      </Footer>
    </Modal>
  );
};