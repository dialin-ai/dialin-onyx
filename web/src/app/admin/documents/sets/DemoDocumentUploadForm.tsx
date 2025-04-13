"use client";

import { Form, Formik } from "formik";
import * as Yup from "yup";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import {
  createDocumentSet,
  updateDocumentSet,
  DocumentSetCreationRequest,
} from "./lib";
import { DocumentSet, UserGroup, ValidSources } from "@/lib/types";
import { TextFormField } from "@/components/admin/connectors/Field";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import React, { useState } from "react";
import { FileUpload } from "@/components/admin/connectors/FileUpload";
import { createConnector } from "@/lib/connector";
import { createCredential, linkCredential } from "@/lib/credential";
import { FileConfig } from "@/lib/connectors/connectors";
import { useUser } from "@/components/user/UserProvider";

interface SetCreationPopupProps {
  onClose: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
  existingDocumentSet?: DocumentSet;
}

export const DemoDocumentUploadForm = ({
  onClose,
  setPopup,
  existingDocumentSet,
}: SetCreationPopupProps) => {
  const isUpdate = existingDocumentSet !== undefined;
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const { user } = useUser();

  return (
    <div className="max-w-full mx-auto">
      <Formik<DocumentSetCreationRequest>
        initialValues={{
          name: existingDocumentSet?.name ?? "",
          description: existingDocumentSet?.description ?? "",
          cc_pair_ids: [],
          is_public: false,
          users: existingDocumentSet?.users ?? [],
          groups: existingDocumentSet?.groups ?? [],
        }}
        validationSchema={Yup.object().shape({
          name: Yup.string().required("Please enter a name for the set"),
          description: Yup.string().optional(),
        })}
        onSubmit={async (values, formikHelpers) => {
          formikHelpers.setSubmitting(true);
          setIsUploading(true);

          try {
            if (selectedFiles.length === 0) {
              setPopup({
                message: "Please select at least one file to upload",
                type: "error",
              });
              setIsUploading(false);
              formikHelpers.setSubmitting(false);
              return;
            }

            // Upload files first
            const formData = new FormData();
            selectedFiles.forEach((file) => {
              formData.append("files", file);
            });

            const uploadResponse = await fetch("/api/manage/admin/connector/file/upload", {
              method: "POST",
              body: formData,
            });
            const uploadResponseJson = await uploadResponse.json();
            if (!uploadResponse.ok) {
              setPopup({
                message: `Unable to upload files - ${uploadResponseJson.detail}`,
                type: "error",
              });
              setIsUploading(false);
              formikHelpers.setSubmitting(false);
              return;
            }

            const filePaths = uploadResponseJson.file_paths as string[];

            // Create a unique name for the connector
            const connectorName = `FileConnector-${values.name}-${Date.now()}`;

            

            // Create a file connector
            const [connectorErrorMsg, connector] = await createConnector<FileConfig>({
              name: connectorName,
              source: ValidSources.File,
              input_type: "load_state",
              connector_specific_config: {
                file_locations: filePaths,
              },
              refresh_freq: null,
              prune_freq: null,
              indexing_start: null,
              access_type: "private",
              groups: values.groups,
            });

            if (connectorErrorMsg || !connector) {
              setPopup({
                message: `Unable to create file connector - ${connectorErrorMsg}`,
                type: "error",
              });
              setIsUploading(false);
              formikHelpers.setSubmitting(false);
              return;
            }

            // Create a unique name for the credential
            const credentialName = `FileCredential-${values.name}-${Date.now()}`;

            // Create a dummy credential for the file connector
            const createCredentialResponse = await createCredential({
              credential_json: {},
              admin_public: false,
              source: ValidSources.File,
              curator_public: false,
              groups: values.groups,
              name: credentialName,
            });

            if (!createCredentialResponse.ok) {
              setPopup({
                message: "Failed to create credential for file connector",
                type: "error",
              });
              setIsUploading(false);
              formikHelpers.setSubmitting(false);
              return;
            }

            const credential = await createCredentialResponse.json();

            console.log(credential);

            // Link the credential to the connector to create a CC pair
            const linkResponse = await linkCredential(
              connector.id,
              credential.id,
              values.name,
              undefined,
              values.groups
            );

            if (!linkResponse.ok) {
              setPopup({
                message: "Failed to create connector-credential pair",
                type: "error",
              });
              setIsUploading(false);
              formikHelpers.setSubmitting(false);
              return;
            }

            const cc_pair_id = (await linkResponse.json()).data;

            // Now create the document set with the CC pair and ensure the current user has access
            const processedValues = {
              ...values,
              cc_pair_ids: [cc_pair_id],
              is_public: false,
              users: user?.id ? [...values.users, user.id] : values.users,
              groups: values.groups,
            };

            let response;
            if (isUpdate) {
              response = await updateDocumentSet({
                id: existingDocumentSet.id,
                ...processedValues,
                users: processedValues.users,
              });
            } else {
              response = await createDocumentSet(processedValues);
            }

            if (response.ok) {
              setPopup({
                message: isUpdate
                  ? "Successfully updated documents!"
                  : "Successfully uploaded documents!",
                type: "success",
              });
              onClose();
            } else {
              const errorJson = await response.json();
              const errorMsg = errorJson.detail || "Unknown error occurred";
              setPopup({
                message: isUpdate
                  ? `Error updating documents - ${errorMsg}`
                  : `Error creating documents - ${errorMsg}`,
                type: "error",
              });
            }
          } catch (error) {
            setPopup({
              message: "An error occurred while processing your request",
              type: "error",
            });
          } finally {
            setIsUploading(false);
            formikHelpers.setSubmitting(false);
          }
        }}
      >
        {(props) => (
          <Form className="space-y-6 w-full">
            <div className="space-y-4 w-full">
              <TextFormField
                name="name"
                label="Name:"
                placeholder="A name for the documents"
                disabled={isUpdate}
                autoCompleteDisabled={true}
              />
              <TextFormField
                name="description"
                label="Description:"
                placeholder="Describe what the documents represent"
                autoCompleteDisabled={true}
                optional={true}
              />
            </div>

            <Separator className="my-6" />

            <div className="space-y-6">
              <FileUpload
                selectedFiles={selectedFiles}
                setSelectedFiles={setSelectedFiles}
                message="Drag and drop files here, or click to select files"
                multiple={true}
              />
            </div>

            <div className="flex mt-6 pt-4 border-t border-neutral-200">
              <Button
                type="submit"
                variant="submit"
                disabled={props.isSubmitting || isUploading}
                className="w-56 mx-auto py-1.5 h-auto text-sm"
              >
                {isUpdate ? "Update" : "Upload"}
              </Button>
            </div>
          </Form>
        )}
      </Formik>
    </div>
  );
};
